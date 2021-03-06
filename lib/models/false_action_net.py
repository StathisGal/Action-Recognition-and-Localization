from __future__ import absolute_import

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from lib.models.resnet_3D import resnet34
from region_net import _RPN
from lib.models.proposal_target_layer_cascade_rois import _ProposalTargetLayer

from lib.roi_packages.roi_align.modules.roi_align import RoIAlignAvg
from lib.utils.net_utils import _smooth_l1_loss

class ACT_net(nn.Module):
    """ action tube proposal """
    def __init__(self, actions):
        super(ACT_net, self).__init__()

        self.classes = actions
        self.n_classes = len(actions)

        # loss
        self.act_loss_cls = 0
        self.act_loss_bbox = 0

        # cfg.POOLING_SIZE
        self.pooling_size = 7
        self.spatial_scale = 1.0/16.0

        # define rpn
        self.act_rpn = _RPN(256)
        self.act_proposal_target = _ProposalTargetLayer(self.n_classes) ## background/ foreground
        self.time_dim =16
        self.temp_scale = 1.
        # self.act_roi_align = RoIAlignAvg(self.pooling_size, self.pooling_size, self.time_dim, self.spatial_scale, self.temp_scale)
        self.act_roi_align = RoIAlignAvg(self.pooling_size, self.pooling_size, self.time_dim, self.spatial_scale)

    def create_architecture(self):
        self._init_modules()
        self._init_weights()

    def forward(self, im_data, im_info, gt_tubes, gt_rois, num_boxes):

        # print('----------Inside----------')
        batch_size = im_data.size(0)
        im_info = im_info.data
        if self.training:
            gt_tubes = gt_tubes.data
            gt_rois =  gt_rois.data
            print('gt_tubes.shape :',gt_tubes.shape)
            print('gt_rois.shape :',gt_rois.shape)
            num_boxes = num_boxes.data

        # feed image data to base model to obtain base feature map
        base_feat = self.act_base(im_data)
        # feed base feature map tp RPN to obtain rois
        rois_all, rpn_loss_cls, rpn_loss_bbox = self.act_rpn(base_feat, im_info, gt_tubes, None, num_boxes)
        print('rois_all.shape : ',rois_all.shape )
        # if it is training phrase, then use ground trubut bboxes for refining
        # firstly find xy- reggression boxes
        if self.training:
            rois = rois_all[:,:,[0,1,2,4,5]] # get pic,x1,y1,x2,y2 coords
            roi_data = self.act_proposal_target(rois, gt_rois, num_boxes)

            rois, rois_label, rois_target, rois_inside_ws, rois_outside_ws = roi_data
            print('rois_label.shape :',rois_label.shape )
            print('rois.shape :',rois.shape )
            rois_label = Variable(rois_label.view(-1).long())
            rois_target = Variable(rois_target.view(-1, rois_target.size(2)))
            rois_inside_ws = Variable(rois_inside_ws.view(-1, rois_inside_ws.size(2)))
            rois_outside_ws = Variable(rois_outside_ws.view(-1, rois_outside_ws.size(2)))
        else:
            rois_label = None
            rois_target = None
            rois_inside_ws = None
            rois_outside_ws = None
            rpn_loss_cls = 0
            rpn_loss_bbox = 0

        rois = Variable(rois)

        # do roi align based on predicted rois
        pooled_feat = self.act_roi_align(base_feat, rois.view(-1,5))
        print('pooled_feat.shape :',pooled_feat.shape)
        # # feed pooled features to top model
        pooled_feat = self._head_to_tail(pooled_feat)
        n_rois = pooled_feat.size(0)

        # # compute bbox offset
        pooled_feat = pooled_feat.mean(2)
        print('pooled_feat.shape :',pooled_feat.shape)
        # ########################################################################

        bbox_pred = self.act_single_frame_pred(pooled_feat)
        print('bbox_pred.shape :',bbox_pred.shape)
        if self.training :
            # select the corresponding columns according to roi labels
            bbox_pred_view = bbox_pred.view(bbox_pred.size(0), int(bbox_pred.size(1) / 4), 4)
            print('bbox_pred_view.shape :',bbox_pred_view.shape)
            print('rois_label.shape :',rois_label.shape)

            bbox_pred_select = torch.gather(bbox_pred_view, 1, rois_label.view(rois_label.size(0), 1, 1).expand(rois_label.size(0), 1, 4))
            bbox_pred = bbox_pred_select.squeeze(1)

        # compute object classification probability
        cls_score = self.act_cls_score(pooled_feat)
        cls_prob = F.softmax(cls_score, 1)

        act_loss_cls = 0
        act_loss_bbox = 0

        if self.training:
            # classification loss
            # print('rois_label :', rois_label)
            act_loss_cls = F.cross_entropy(cls_score, rois_label)


            # bounding box regression L1 loss
            act_loss_bbox = _smooth_l1_loss(bbox_pred, rois_target, rois_inside_ws, rois_outside_ws)

            
        bbox_pred = bbox_pred.view(batch_size, rois.size(1), -1)
        print('rois.shape :', rois.shape)
        print('rois :',rois)

        print('bbox_pred.shape :',bbox_pred.shape)
        if self.training:
            return rois,  bbox_pred, cls_prob, rpn_loss_cls, rpn_loss_bbox, act_loss_cls, act_loss_bbox

        return rois,  bbox_pred, cls_prob,

    def _init_weights(self):
        def normal_init(m, mean, stddev, truncated=False):
            """
            weight initalizer: truncated normal and random normal.
            """
            # x is a parameter
            if truncated:
                m.weight.data.normal_().fmod_(2).mul_(stddev).add_(mean) # not a perfect approximation
            else:
                m.weight.data.normal_(mean, stddev)
                m.bias.data.zero_()

        truncated = False
        normal_init(self.act_rpn.RPN_Conv, 0, 0.01, truncated)
        normal_init(self.act_rpn.RPN_cls_score, 0, 0.01, truncated)
        normal_init(self.act_rpn.RPN_bbox_pred, 0, 0.01, truncated)
        # normal_init(self.act_bbox_pred, 0, 0.001, truncated)
        normal_init(self.act_cls_score, 0, 0.001, truncated)
        normal_init(self.act_single_frame_pred, 0, 0.001, truncated)

    def _init_modules(self):

        resnet_shortcut = 'A'
        sample_size = 112
        sample_duration = 16  # len(images)

        model = resnet34(num_classes=400, shortcut_type=resnet_shortcut,
                         sample_size=sample_size, sample_duration=sample_duration,
                         last_fc=False)
        model = model
        model = nn.DataParallel(model, device_ids=None)

        self.model_path = '../temporal_localization/resnet-34-kinetics.pth'
        print("Loading pretrained weights from %s" %(self.model_path))
        model_data = torch.load(self.model_path)
        model.load_state_dict(model_data['state_dict'])
        # Build resnet.
        self.act_base = nn.Sequential(model.module.conv1, model.module.bn1, model.module.relu,
          model.module.maxpool,model.module.layer1,model.module.layer2, model.module.layer3)

        self.act_top = nn.Sequential(model.module.layer4)

        # self.act_bbox_pred = nn.Linear(512, 6 ) # 2 classes bg/ fg
        # self.act_bbox_pred = nn.Linear(8192, 6 * self.n_classes) # 2 classes bg/ fg
        # self.act_cls_score = nn.Linear(8192, self.n_classes)
        self.act_single_frame_pred = nn.Linear(512, 4 * self.n_classes)
        # self.act_bbox_pred = nn.Linear(512, 6 * self.n_classes) # 2 classes bg/ fg
        self.act_cls_score = nn.Linear(512, self.n_classes)

        # Fix blocks
        for p in self.act_base[0].parameters(): p.requires_grad=False
        for p in self.act_base[1].parameters(): p.requires_grad=False

        fixed_blocks = 3
        if fixed_blocks >= 3:
          for p in self.act_base[6].parameters(): p.requires_grad=False
        if fixed_blocks >= 2:
          for p in self.act_base[5].parameters(): p.requires_grad=False
        if fixed_blocks >= 1:
          for p in self.act_base[4].parameters(): p.requires_grad=False

        def set_bn_fix(m):
          classname = m.__class__.__name__
          if classname.find('BatchNorm') != -1:
            for p in m.parameters(): p.requires_grad=False

        self.act_base.apply(set_bn_fix)
        self.act_top.apply(set_bn_fix)


    def _head_to_tail(self, pool5):
        # print('pool5.shape :',pool5.shape)
        batch_size = pool5.size(0)
        fc7 = self.act_top(pool5)
        fc7 = fc7.mean(4)
        fc7 = fc7.mean(3) # exw (bs,512,16)

        # print('fc7.shape :',fc7.shape)
        return fc7

    
