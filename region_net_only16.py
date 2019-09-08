from __future__ import absolute_import
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from config import cfg
from proposal_layer import _ProposalLayer
from proposal_layer_xy import _ProposalLayer_xy
from anchor_target_layer_mine import _AnchorTargetLayer
from anchor_target_layer_xy import _AnchorTargetLayer_xy
from net_utils import _smooth_l1_loss, get_number_of_combinations

import numpy as np
import math
import pdb
import time

class _RPN(nn.Module):
    """ region proposal network """
    def __init__(self, din, sample_duration):
        super(_RPN, self).__init__()
        

        self.din = din  # get depth of input feature map, e.g., 512
        self.sample_duration =sample_duration # get sample_duration

        self.anchor_scales = [1, 2, 4, 8, 16]
        self.anchor_ratios = [0.5, 1, 2]
        self.feat_stride = [16, ]
        
        self.anchor_duration = [sample_duration] # add 

        # # define the convrelu layers processing input feature map
        self.RPN_Conv = nn.Conv3d(self.din, self.din, 3, stride=1, padding=1, bias=True)

        self.nc_score_out = len(self.anchor_scales) * len(self.anchor_ratios) *  2
        self.RPN_cls_score = nn.Conv3d(self.din, self.nc_score_out, 1, 1, 0)

        # define anchor box offset prediction layer

        self.nc_bbox_out = len(self.anchor_scales) * len(self.anchor_ratios) * self.sample_duration * 4
        self.RPN_bbox_pred = nn.Conv3d(self.din, self.nc_bbox_out, 1, 1, 0) # for regression

        # define proposal layer
        self.RPN_proposal = _ProposalLayer(self.feat_stride, self.anchor_scales, self.anchor_ratios, self.anchor_duration,  len(self.anchor_scales) * len(self.anchor_ratios) )

        # define anchor target layer
        self.RPN_anchor_target = _AnchorTargetLayer(self.feat_stride,  self.anchor_scales, self.anchor_ratios, self.anchor_duration, None)

        # self.avg_pool = nn.MaxPool3d((self.sample_duration,1,1), stride=1)
        # self.avg_pool_3_4 = nn.MaxPool3d((int(sample_duration*3/4),1,1), stride=1)
        # self.avg_pool_2 = nn.MaxPool3d((int(sample_duration/2),1,1), stride=1)
        # self.avg_pool_4 = nn.MaxPool3d((int(sample_duration/4),1,1), stride=1)

        self.avg_pool = nn.AvgPool3d((self.sample_duration,1,1), stride=1)

        self.rpn_loss_cls = 0
        self.rpn_loss_box = 0

    @staticmethod
    def reshape(x, d):
        input_shape = x.size()
        x = x.view(
            input_shape[0],
            int(d),
            int(float(input_shape[1] * input_shape[2]) / float(d)),
            input_shape[3],
            input_shape[4]
        )
        return x

    @staticmethod
    def reshape2d(x, d):
        input_shape = x.size()
        x = x.view(
            input_shape[0],
            int(d),
            int(float(input_shape[1] * input_shape[2]) / float(d)),
            input_shape[3],
        )
        return x


    def forward(self, base_feat, im_info, gt_boxes, gt_rois):

        batch_size = base_feat.size(0)

        rpn_conv1 = F.relu(self.RPN_Conv(base_feat), inplace=True) # 3d convolution

        rpn_conv_avg = self.avg_pool(rpn_conv1)
        rpn_cls_score = self.RPN_cls_score(rpn_conv_avg)  # classification layer
        rpn_bbox_pred = self.RPN_bbox_pred(rpn_conv_avg)  # regression layer

        # batch_size = 2
        rpn_cls_score_reshape = self.reshape(rpn_cls_score, 2)
        rpn_cls_prob_reshape = F.softmax(rpn_cls_score_reshape, 1)
        rpn_cls_prob = self.reshape(rpn_cls_prob_reshape, self.nc_score_out)

        # proposal layer
        cfg_key = 'TRAIN' if self.training else 'TEST'

        rois = self.RPN_proposal((rpn_cls_prob.data, rpn_bbox_pred.data, im_info, cfg_key))

        self.rpn_loss_cls = 0
        self.rpn_loss_box = 0


        # generating training labels a# nd build the rpn loss
        if self.training:

            assert gt_rois is not None

            ## Regular data
            rpn_data = self.RPN_anchor_target((rpn_cls_score.data, 
                                               gt_boxes, im_info,    \
                                               gt_rois)) # time_limit = 16

            ## 16 frames
            rpn_cls_score = rpn_cls_score_reshape.permute(0, 2, 3, 4,1).contiguous()
            rpn_cls_score = rpn_cls_score.view(batch_size, -1, 2) ## exw [1, 441, 2]

            rpn_label_ = rpn_data[0].view(batch_size, -1)
            rpn_keep_ = Variable(rpn_label_.view(-1).ne(-1).nonzero().view(-1))

            rpn_cls_score = torch.index_select(rpn_cls_score.view(-1,2), 0, rpn_keep_)

            rpn_label_ = torch.index_select(rpn_label_.view(-1), 0, rpn_keep_.data)
            rpn_label_ = Variable(rpn_label_.long())

            self.rpn_loss_cls =  F.cross_entropy(rpn_cls_score, rpn_label_)


            # Rest stuff
            rpn_bbox_targets_, rpn_bbox_inside_weights_,\
            rpn_bbox_outside_weights_ = rpn_data[1:]

            rpn_bbox_inside_weights_ = Variable(rpn_bbox_inside_weights_)
            rpn_bbox_outside_weights_ = Variable(rpn_bbox_outside_weights_)
            rpn_bbox_targets_ = Variable(rpn_bbox_targets_)

            self.rpn_loss_box =  _smooth_l1_loss(rpn_bbox_pred, rpn_bbox_targets_, rpn_bbox_inside_weights_,
                                                               rpn_bbox_outside_weights_, sigma=3,dim=[1,2,3,4])

        return rois, None, self.rpn_loss_cls, self.rpn_loss_box, None, None


if __name__ == '__main__':

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    # a good example is v_TrampolineJumping_g17_c01
    # feats = torch.rand(1,512,16,4,4).cuda()
    # feats = torch.rand(1,512,8,4,4).cuda().float()
    feats = torch.rand(2,256,16,7,7).float().to(device)
    gt_bboxes = torch.Tensor([[[42., 44.,  0., 68., 98., 15., 11.]],
                              [[34., 52.,  0., 67., 98., 15., 11.]]]).to(device)
    im_info = torch.Tensor([[112,112,16],[112,112,16]]).to(device)
    n_actions = torch.Tensor([1,1]).to(device)
    model = _RPN(256).to(device)
    out = model(feats,im_info, gt_bboxes, None, n_actions)

