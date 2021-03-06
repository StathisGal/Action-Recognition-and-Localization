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
import numpy.random as npr
from config.config import cfg
from lib.utils.bbox_transform import bbox_overlaps_batch_3d, bbox_transform_batch_3d


class _Regression_Target(nn.Module):
    """
    Assign object detection proposals to ground-truth targets. Produces proposal
    classification labels and bounding-box regression targets.
    """

    def __init__(self, nclasses, sample_duration):
        super(_Regression_Target, self).__init__()
        self._num_classes = nclasses
        self.sample_duration = sample_duration
        self.BBOX_NORMALIZE_MEANS = torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_MEANS)
        self.BBOX_NORMALIZE_STDS = torch.FloatTensor(cfg.TRAIN.BBOX_NORMALIZE_STDS)
        self.BBOX_INSIDE_WEIGHTS = torch.FloatTensor(cfg.TRAIN.BBOX_INSIDE_WEIGHTS)

    def forward(self, all_tubes, gt_boxes,num_boxes):

        self.BBOX_NORMALIZE_MEANS = self.BBOX_NORMALIZE_MEANS.type_as(gt_boxes)
        self.BBOX_NORMALIZE_STDS  = self.BBOX_NORMALIZE_STDS.type_as(gt_boxes)
        self.BBOX_INSIDE_WEIGHTS  = self.BBOX_INSIDE_WEIGHTS.type_as(gt_boxes)

        batch_size = all_tubes.size(0)
        offset = torch.arange(0,self.sample_duration).type_as(gt_boxes)
        offset = offset.unsqueeze(1).expand(offset.size(0),self.sample_duration)
        # offset_batch = torch.arange(0,batch_size).type_as(gt_boxes)
        # offset_batch = offset_batch.unsqueeze(1)
        print('offset :',offset)
        print('offset :',offset.shape)
        print('all_tubes.shape:',all_tubes.shape)
        all_rois = torch.zeros(batch_size,all_tubes.size(1),self.sample_duration,5)
        print('all_rois.shape :',all_rois.shape)
        all_tubes = all_tubes.unsqueeze(2).expand(all_tubes.size(0), all_tubes.size(1),gt_boxes.size(2),all_tubes.size(2))
        print('all_tubes.shape:',all_tubes.shape)
        print('all_tubes :',all_tubes)
        
        all_tubes = all_tubes.contiguous().view(batch_size,-1,all_tubes.size(3))
    

        num_boxes = num_boxes.long()
        gt_boxes_append = gt_boxes.new(gt_boxes.size()).zero_()
        gt_boxes_append[:,:,1:] = gt_boxes[:,:,:7] # in pos 0 is the score
        # gt_boxes_append[:,:,1:] = gt_boxes[:,:,:6] # in pos 0 is the score
        num_rois_pre = all_rois.size(1)
        # print('all_rois.shape :',all_rois.shape )
        # print('nu_rois_pre :', num_rois_pre )

        # print('gt_boxes_append.shape :',gt_boxes_append.shape)
        # print('gt_boxes_append :',gt_boxes_append)
        # Include ground-truth boxes in the set of candidate rois
        # print('all_rois.shape :',all_rois.shape )
        all_rois = torch.cat([all_rois, gt_boxes_append], 1)

        num_images = 1
        rois_per_image = int(cfg.TRAIN.BATCH_SIZE / num_images)
        fg_rois_per_image = int(np.round(cfg.TRAIN.FG_FRACTION * rois_per_image))
        fg_rois_per_image = 1 if fg_rois_per_image == 0 else fg_rois_per_image

        labels, rois, bbox_targets, bbox_inside_weights = self._sample_rois_pytorch(
            all_rois, gt_boxes, fg_rois_per_image,
            rois_per_image, self._num_classes, num_boxes, num_rois_pre)

        bbox_outside_weights = (bbox_inside_weights > 0).float()
        # print('inside cascade rois :',rois)
        return rois, labels, bbox_targets, bbox_inside_weights, bbox_outside_weights

    def backward(self, top, propagate_down, bottom):
        """This layer does not propagate gradients."""
        pass

    def reshape(self, bottom, top):
        """Reshaping happens during the call to forward."""
        pass

    def _get_bbox_regression_labels_pytorch(self, bbox_target_data, labels_batch, num_classes):
        """Bounding-box regression targets (bbox_target_data) are stored in a
        compact form b x N x (class, tx, ty, tz, tw, th, tt)

        This function expands those targets into the 4-of-4*K representation used
        by the network (i.e. only one class has non-zero targets).

        Returns:
            bbox_target (ndarray): b x N x 4K blob of regression targets
            bbox_inside_weights (ndarray): b x N x 4K blob of loss weights
        """
        batch_size = labels_batch.size(0)
        rois_per_image = labels_batch.size(1)
        clss = labels_batch
        bbox_targets = bbox_target_data.new(batch_size, rois_per_image, 6).zero_()
        bbox_inside_weights = bbox_target_data.new(bbox_targets.size()).zero_()

        for b in range(batch_size):
            # assert clss[b].sum() > 0
            if clss[b].sum() == 0:
                continue
            inds = torch.nonzero(clss[b] > 0).view(-1)
            for i in range(inds.numel()):
                ind = inds[i]
                bbox_targets[b, ind, :] = bbox_target_data[b, ind, :]
                bbox_inside_weights[b, ind, :] = self.BBOX_INSIDE_WEIGHTS

        return bbox_targets, bbox_inside_weights


    def _compute_targets_pytorch(self, ex_rois, gt_rois):
        """Compute bounding-box regression targets for an image."""
        # print('ex_rois.shape :',ex_rois.shape)
        # print('gt_rois.shape :',gt_rois.shape)
        assert ex_rois.size(1) == gt_rois.size(1)
        assert ex_rois.size(2) == 6
        assert gt_rois.size(2) == 6

        batch_size = ex_rois.size(0)
        rois_per_image = ex_rois.size(1)

        targets = bbox_transform_batch_3d(ex_rois, gt_rois)
        # print('targets.shape :',targets.shape)
        if cfg.TRAIN.BBOX_NORMALIZE_TARGETS_PRECOMPUTED:
            # Optionally normalize targets by a precomputed mean and stdev
            targets = ((targets - self.BBOX_NORMALIZE_MEANS.expand_as(targets))
                        / self.BBOX_NORMALIZE_STDS.expand_as(targets))

        return targets


    def _sample_rois_pytorch(self, all_rois, gt_boxes, fg_rois_per_image, rois_per_image, num_classes,num_boxes, num_rois_pre):
        """Generate a random sample of RoIs comprising foreground and background
        examples.
        """
        # overlaps: (rois x gt_boxes)
        # print('all_rois :',all_rois)
        overlaps = bbox_overlaps_batch_3d(all_rois, gt_boxes)

        # print('overlaps.shape :',overlaps.shape)
        max_overlaps, gt_assignment = torch.max(overlaps, 2)

        batch_size = overlaps.size(0)
        num_proposal = overlaps.size(1)
        num_boxes_per_img = overlaps.size(2)

        offset = torch.arange(0, batch_size)*gt_boxes.size(1)
        offset = offset.view(-1, 1).type_as(gt_assignment) + gt_assignment
        # print('offset :',offset)
        labels = gt_boxes[:,:,6].contiguous().view(-1)[(offset.view(-1),)].view(batch_size, -1)

        n_last_dim = all_rois.size(2)
        # print('n_last_dim :',n_last_dim)
        labels_batch = labels.new(batch_size, rois_per_image).zero_()
        rois_batch  = all_rois.new(batch_size, rois_per_image, n_last_dim).zero_()
        # gt_rois_batch = all_rois.new().zero_()
        gt_rois_batch = torch.zeros(batch_size, rois_per_image, n_last_dim).to(rois_batch.device)
        # Guard against the case when an image has fewer than max_fg_rois_per_image
        # foreground RoIs

        for i in range(batch_size):
            gt_boxes_single = gt_boxes[i,:num_boxes[i]]
            # print(gt_boxes_single.shape)
            # print('gt_boxes[:num_boxes[i]] :',gt_boxes_single)
            if gt_boxes_single[:,:7].byte().any() == 0:
                print('no rois')
                continue
            
            
        
            max_overlaps_single =max_overlaps[i][:num_boxes[i]+num_rois_pre]
            fg_inds = torch.nonzero(max_overlaps_single >= cfg.TRAIN.FG_THRESH).view(-1)
            fg_num_rois = fg_inds.numel()

            # Select background RoIs as those within [BG_THRESH_LO, BG_THRESH_HI)
            bg_inds = torch.nonzero((max_overlaps_single < cfg.TRAIN.BG_THRESH_HI) &
                                    (max_overlaps_single >= cfg.TRAIN.BG_THRESH_LO)).view(-1)
            bg_num_rois = bg_inds.numel()

            if fg_num_rois > 0 and bg_num_rois > 0:
                # sampling fg
                fg_rois_per_this_image = min(fg_rois_per_image, fg_num_rois)
                rand_num = torch.from_numpy(np.random.permutation(fg_num_rois)).type_as(gt_boxes).long()
                fg_inds = fg_inds[rand_num[:fg_rois_per_this_image]]

                # sampling bg
                bg_rois_per_this_image = rois_per_image - fg_rois_per_this_image

                rand_num = np.floor(np.random.rand(bg_rois_per_this_image) * bg_num_rois)
                rand_num = torch.from_numpy(rand_num).type_as(gt_boxes).long()
                bg_inds = bg_inds[rand_num]

            elif fg_num_rois > 0 and bg_num_rois == 0:

                # sampling fg
                rand_num = np.floor(np.random.rand(rois_per_image) * fg_num_rois)
                rand_num = torch.from_numpy(rand_num).type_as(gt_boxes).long()
                fg_inds = fg_inds[rand_num]
                fg_rois_per_this_image = rois_per_image
                bg_rois_per_this_image = 0

            elif bg_num_rois > 0 and fg_num_rois == 0:

                # sampling bg
                rand_num = np.floor(np.random.rand(rois_per_image) * bg_num_rois)
                rand_num = torch.from_numpy(rand_num).type_as(gt_boxes).long()

                bg_inds = bg_inds[rand_num]
                bg_rois_per_this_image = rois_per_image
                fg_rois_per_this_image = 0
            else:
                print('gt_boxes :',gt_boxes)
                print('i :',i)
                print('gt_boxes_single :',gt_boxes_single)
                print('max_overlaps_single :',max_overlaps_single.cpu().tolist())
                print('num_boxes[i] :',num_boxes[i])
                print('num_rois_pre :',num_rois_pre)
                print('all_rois :',all_rois.cpu().tolist())
                raise ValueError("bg_num_rois = 0 and fg_num_rois = 0, this should not happen!")

            # The indices that we're selecting (both fg and bg)
            keep_inds = torch.cat([fg_inds, bg_inds], 0)
            # Select sampled values from various arrays:
            labels_batch[i].copy_(labels[i][keep_inds])

            # Clamp labels for the background RoIs to 0
            if fg_rois_per_this_image < rois_per_image:
                labels_batch[i][fg_rois_per_this_image:] = 0
            rois_batch[i] = all_rois[i,keep_inds]
            rois_batch[i,:,0] = i

            gt_rois_batch[i] = gt_boxes[i][gt_assignment[i][keep_inds]]

        bbox_target_data = self._compute_targets_pytorch(
                rois_batch[:,:,1:7], gt_rois_batch[:,:,:6])

        bbox_targets, bbox_inside_weights = \
                self._get_bbox_regression_labels_pytorch(bbox_target_data, labels_batch, num_classes)

        return labels_batch, rois_batch, bbox_targets, bbox_inside_weights
