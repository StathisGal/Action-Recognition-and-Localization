from __future__ import absolute_import
# --------------------------------------------------------
# Faster R-CNN
# Copyright (c) 2015 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by Ross Girshick and Sean Bell
# --------------------------------------------------------
# --------------------------------------------------------
# Reorganized and modified by Jianwei Yang and Jiasen Lu
# --------------------------------------------------------

import torch
import torch.nn as nn
import numpy as np
import math
import yaml
from config import cfg
from generate_3d_anchors import generate_anchors
from bbox_transform import bbox_transform_inv, clip_boxes_3d, clip_boxes_batch, bbox_transform_inv_3d

import pdb

DEBUG = False

class _ProposalLayer(nn.Module):
    """
    Outputs object detection proposals by applying estimated bounding-box
    transformations to a set of regular boxes (called "anchors").
    """

    def __init__(self, feat_stride, scales, ratios, time_dim):
        super(_ProposalLayer, self).__init__()

        # self.sample_duration = time_dim
        self._feat_stride = feat_stride
        self._anchors = torch.from_numpy(generate_anchors(scales=np.array(scales), 
                                                          ratios=np.array(ratios),
                                                          time_dim=np.array(time_dim))).float()
        self._num_anchors = self._anchors.size(0)
        # rois blob: holds R regions of interest, each is a 5-tuple
        # (n, x1, y1, x2, y2) specifying an image batch index n and a
        # rectangle (x1, y1, x2, y2)
        # top[0].reshape(1, 5)
        #
        # # scores blob: holds scores for R regions of interest
        # if len(top) > 1:
        #     top[1].reshape(1, 1, 1, 1)

    def forward(self, input):

        # Algorithm:
        #
        # for each (H, W) location i
        #   generate A anchor boxes centered on cell i
        #   apply predicted bbox deltas at cell i to each of the A anchors
        # clip predicted boxes to image
        # remove predicted boxes with either height or width < threshold
        # sort all (proposal, score) pairs by score from highest to lowest
        # take top pre_nms_topN proposals before NMS
        # apply NMS with threshold 0.7 to remaining proposals
        # take after_nms_topN proposals after NMS
        # return the top proposals (-> RoIs top, scores top)


        # the first set of _num_anchors channels are bg probs
        # the second set are the fg probs

        scores = input[0][:, self._num_anchors:, :, :]
        bbox_frame = input[1]
        im_info = input[2]
        cfg_key = input[3]
        time_dim = input[4]
        # print('bbox_frame.shape :',bbox_frame.shape)

        batch_size = bbox_frame.size(0)
        # print('batch_size : ', batch_size)
        # pre_nms_topN  = cfg[cfg_key].RPN_PRE_NMS_TOP_N
        # post_nms_topN = cfg[cfg_key].RPN_POST_NMS_TOP_N
        # nms_thresh    = cfg[cfg_key].RPN_NMS_THRESH
        # min_size      = cfg[cfg_key].RPN_MIN_SIZE
        if cfg_key == 'TRAIN':
            pre_nms_topN  = 20000
            # post_nms_topN = 50
            post_nms_topN = 100
            nms_thresh    = 0.7
            min_size      = 8
        else:
            pre_nms_topN  = 6000
            post_nms_topN = 25
            # post_nms_topN = 10
            nms_thresh    = 0.7
            min_size      = 16

        ##################
        # Create anchors #
        ##################

        # print('batch_size :', batch_size)
        feat_time, feat_height,  feat_width= scores.size(2), scores.size(3), scores.size(4) # (batch_size, 512/256, 7,7, 16/8)
        shift_x = np.arange(0, feat_width) * self._feat_stride
        shift_y = np.arange(0, feat_height) * self._feat_stride
        shift_z = np.arange(0, feat_time ) # z dim is time dim
        shift_x, shift_y, shift_z = np.meshgrid(shift_x, shift_y, shift_z)
        shifts = torch.from_numpy(np.vstack((shift_x.ravel(), shift_y.ravel(), shift_z.ravel(),
                                             shift_x.ravel(), shift_y.ravel(), shift_z.ravel())).transpose())
        shifts = shifts.contiguous().type_as(scores).float()
        # print('shifts.shape :',shifts.shape)
        # print('shift_x {} shift_y {} shift_z {}'.format(shift_x , shift_y ,shift_z ))
        A = self._num_anchors
        K = shifts.size(0)

        self._anchors = self._anchors.type_as(scores)

        anchors = self._anchors.view(1, A, 6) + shifts.view(K, 1, 6)
        anchors = anchors.view(1, K * A, 6)
        # print('anchors.shape :', anchors.shape)
        anchors = anchors.expand(batch_size, K * A, 6)

        # print('anchors.shape :', anchors.shape)

        # Transpose and reshape predicted bbox transformations to get them
        # into the same order as the anchors:
        # print('bbox_frame.shape :', bbox_frame.shape) # 216 * 7 * 7 * 16/8 frames, 216 = 36 (anchors) * 6 (x1,y1,t1,x2,y2,t2)

        bbox_frame = bbox_frame.permute(0, 2, 3, 4, 1).contiguous()
        # print('bbox_frame.shape :', bbox_frame.shape) # 216 * 7 * 7 * 16/8 frames, 216 = 36 (anchors) * 6 (x1,y1,t1,x2,y2,t2)
        bbox_frame = bbox_frame.view(batch_size, -1, 6)
        # print('bbox_frame.shape :', bbox_frame.shape) # 216 * 7 * 7 * 16/8 frames, 216 = 36 (anchors) * 6 (x1,y1,t1,x2,y2,t2)

        # Same story for the scores:
        # print('scores.shape :', scores.shape) # 216 * 7 * 7 * 16/8 frames, 216 = 36 (anchors) * 6 (x1,y1,t1,x2,y2,t2)
        scores = scores.permute(0, 2, 3, 4, 1).contiguous()
        # print('scores.shape :', scores.shape) # 216 * 7 * 7 * 16/8 frames, 216 = 36 (anchors) * 6 (x1,y1,t1,x2,y2,t2)
        scores = scores.view(batch_size, -1)
        # print('scores.shape :', scores.shape) # 216 * 7 * 7 * 16/8 frames, 216 = 36 (anchors) * 6 (x1,y1,t1,x2,y2,t2)
        ###############################
        # Until now, everything is ok #
        ###############################
        """
        we have 16 frames, and 28224 3d anchors for each 16 frames
        """
        # Convert anchors into proposals via bbox transformations
        # proposals = bbox_frames_transform_inv(anchors, bbox_deltas, batch_size)
        proposals = bbox_transform_inv_3d(anchors, bbox_frame, batch_size) # proposals have 441 * time_dim shape
        # print('proposals.shape :',proposals.shape)
        # print('proposals :',proposals)

        # 2. clip predicted boxes to image
        ## if any dimension exceeds the dims of the original image, clamp_ them
        # print('proposals.shape :',proposals.shape)
        # print('im_info.shape :',im_info.shape)
        proposals = clip_boxes_3d(proposals, im_info, batch_size)
        scores_keep = scores
        proposals_keep = proposals

        _, order = torch.sort(scores, 1, True)
        
        output = scores.new(batch_size, post_nms_topN, 8).zero_()
        # print('output.shape :',output.shape)
        for i in range(batch_size):
            # # 3. remove predicted boxes with either height or width < threshold
            # # (NOTE: convert min_size to input image scale stored in im_info[2])
            proposals_single = proposals_keep[i]
            scores_single = scores_keep[i]
            # print('scores_single.shape :',scores_single.shape)
            # # 4. sort all (proposal, score) pairs by score from highest to lowest
            # # 5. take top pre_nms_topN (e.g. 6000)
            order_single = order[i]

            proposals_single = proposals_single[order_single, :]
            scores_single = scores_single[order_single].view(-1,1)
            proposals_single = proposals_single[:post_nms_topN, :]
            scores_single = scores_single[:post_nms_topN]
            
            # adding score at the end.
            num_proposal = proposals_single.size(0)
            output[i,:num_proposal,0] = i
            output[i,:num_proposal,1:7] = proposals_single
            output[i,:num_proposal,7] = scores_single.squeeze()

        # print('output.shape :',output.shape)
        # print('output :',output)
        return output

    def backward(self, top, propagate_down, bottom):
        """This layer does not propagate gradients."""
        pass

    def reshape(self, bottom, top):
        """Reshaping happens during the call to forward."""
        pass

    def _filter_boxes(self, boxes, min_size):
        """Remove all boxes with any side smaller than min_size."""
        ws = boxes[:, :, 2] - boxes[:, :, 0] + 1
        hs = boxes[:, :, 3] - boxes[:, :, 1] + 1
        keep = ((ws >= min_size.view(-1,1).expand_as(ws)) & (hs >= min_size.view(-1,1).expand_as(hs)))
        return keep
