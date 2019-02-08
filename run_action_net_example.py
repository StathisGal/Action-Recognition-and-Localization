import os
import numpy as np
import glob
import json

import torch
import torch.nn as nn
from torch.autograd import Variable
from torch.utils.data import DataLoader

from resnet_3D import resnet34
from video_dataset import Video
from spatial_transforms import (
    Compose, Normalize, Scale, CenterCrop, ToTensor, Resize)
from temporal_transforms import LoopPadding

from action_net import ACT_net

if __name__ == '__main__':

    # torch.cuda.device_count()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print("Device being used:", device)

    dataset_folder = '/gpu-data/sgal/UCF-101-frames'
    boxes_file = './pyannot.pkl'
    # boxes_file = '/gpu-data/sgal/UCF-bboxes.json'
    # dataset_folder = '../UCF-101-frames'
    # boxes_file = '../UCF-101-frames/UCF-bboxes.json'

    sample_size = 112
    # sample_duration = 8 #16  # len(images)
    sample_duration = 16  # len(images)
    batch_size = 1
    n_threads = 0

    # # get mean
    # mean =  [103.75581543 104.79421473  91.16894564] # jhmdb
    mean = [103.29825354, 104.63845484,  90.79830328]  # jhmdb from .png

    # generate model
    last_fc = False

    # classes = ['basketballdunk', 'basketballshooting','cliffdiving', 'cricketbowling', 'fencing', 'floorgymnastics',
    #            'icedancing', 'longjump', 'polevault', 'ropeclimbing', 'salsaspin', 'skateboarding',
    #            'skiing', 'skijet', 'surfing', 'biking', 'diving', 'golfswing', 'horseriding',
    #            'soccerjuggling', 'tennisswing', 'trampolinejumping', 'volleyballspiking', 'walking']
    actions = ['Basketball','BasketballDunk','Biking','CliffDiving','CricketBowling',
               'Diving','Fencing','FloorGymnastics','GolfSwing','HorseRiding','IceDancing',
               'LongJump','PoleVault','RopeClimbing','SalsaSpin','SkateBoarding','Skiing',
               'Skijet','SoccerJuggling','Surfing','TennisSwing','TrampolineJumping',
               'VolleyballSpiking','WalkingWithDog']

    cls2idx = {actions[i]: i for i in range(0, len(actions))}

    spatial_transform = Compose([Scale(sample_size),  # [Resize(sample_size),
                                 ToTensor(),
                                 Normalize(mean, [1, 1, 1])])
    temporal_transform = LoopPadding(sample_duration)

    data = Video(dataset_folder, frames_dur=sample_duration, spatial_transform=spatial_transform,
                 temporal_transform=temporal_transform, json_file=boxes_file,
                 mode='train', classes_idx=cls2idx)
    # data_loader = torch.utils.data.DataLoader(data, batch_size=batch_size,
    #                                           shuffle=True, num_workers=n_threads, pin_memory=True)


    # for i in range(700,850):
    #     k = data[i]
    #     print('abs path :',k[4], ' i :',i)
    
    
    # clips,  (h, w), gt_tubes, final_rois = data[906]
    # clips,  (h, w), gt_tubes, final_rois = data[905]
    clips,  (h, w), gt_tubes, gt_rois = data[1451]

    print('clips.shape :',clips.shape)
    clips = clips.unsqueeze(0)
    gt_tubes = gt_tubes.unsqueeze(0)
    print('gt_rois.shape :',gt_rois.shape)
    # print('h :', h, ' w :', w)
    # print('gt_tubes :', gt_tubes)
    # print('final_rois :', final_rois)
    # print('type final_rois: ', type(final_rois))

    # n_classes = len(classes)

    model = ACT_net(actions).cuda()
    inputs = Variable(clips).cuda()

    rois,  bbox_pred, rpn_loss_cls, rpn_loss_bbox,  act_loss_bbox, rois_label = model(inputs,
                                                                                    torch.Tensor([[h, w]] * gt_tubes.size(1)).cuda(),
                                                                                      gt_tubes.cuda(), gt_rois.cuda(),
                                                                                      torch.Tensor(len(gt_tubes)).cuda())
    print('rois.shape :',rois.shape)
    print('bbox_pred.shape :', bbox_pred)
    print('rpn_loss_cls.shape :',rpn_loss_cls)
    print('act_loss_bbox.shape :',act_loss_bbox)
    print('rois_label.shape :',rois_label)


    # with open('./outputs.json', 'w') as fp:
    #     json.dump(outputs_list, fp)
    
    # rois, rpn_loss_cls, rpn_loss_box = rpn_model(outputs,
    #                                              torch.Tensor(
    #                                                  [[h, w]] * gt_tubes.size(1)).cuda(),
    #                                              gt_tubes.cuda(), gt_rois, len(gt_tubes))
