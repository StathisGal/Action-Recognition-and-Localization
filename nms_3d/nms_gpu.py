from __future__ import absolute_import
import torch
import numpy as np
from torch.nn.modules.module import Module

from _ext import nms
# from ._ext import nms

import pdb

def nms_gpu(dets, thresh):

        # dets = dets.contiguous()
        keep = dets.new(dets.size(0), 1).zero_().int()
        num_out = dets.new(1).zero_().int()
        nms.nms_cuda(keep, dets, num_out, thresh)
        keep = keep[:num_out[0]]

        return keep

# class nms_gpu(Module):

#     def __init__(self, thresh):
#         super(nms_gpu, self).__init__()

#         self.thresh = float(thresh)

#     def forward(self, dets):

#         keep = dets.new(dets.size(0), 1).zero_().int()
#         num_out = dets.new(1).zero_().int()
#         nms.nms_cuda(keep, dets, num_out, self.thresh)
#         keep = keep[:num_out[0]]

#         return keep

if __name__ == '__main__':
        t = torch.Tensor([[ 26.4898,  34.4385,  51.8522,  82.3893,  28.1600,  34.4226,  53.4678,
                            82.4395,  26.4744,  34.2483,  51.7999,  82.5446,  28.6425,  34.0756,
                            54.0439,  82.1535,  26.6081,  34.1177,  52.0324,  82.3781,  26.5650,
                            34.0801,  51.8505,  82.4499,  26.4622,  34.0807,  51.9115,  82.4355,
                            26.5257,  33.9332,  51.9047,  82.2246,  26.4699,  34.1244,  51.9585,
                            82.2706,  26.5596,  34.7838,  52.0329,  83.0380,  26.6254,  34.1967,
                            52.0659,  82.5796,  26.5861,  34.2553,  52.0830,  82.4695,  26.5242,
                            34.3406,  52.1313,  82.5145,  26.4408,  34.2800,  52.0937,  82.4439,
                            26.4098,  34.4563,  51.9639,  82.5084,  26.4212,  34.1052,  51.9917,
                            82.2834],
                          [ 28.0395,  38.7344,  52.7309,  73.9631,  28.0357,  38.7232,  52.8115,
                            73.9151,  27.1504,  38.6799,  52.0752,  73.8793,  27.9596,  38.7229,
                            52.9116,  73.9364,  27.1223,  38.2307,  52.0985,  73.3536,  27.0169,
                            38.2198,  52.1111,  73.3368,  26.9757,  38.8533,  52.1651,  73.8930,
                            26.9291,  38.3716,  52.1105,  73.4578,  26.8378,  38.8499,  52.1247,
                            73.8385,  26.7392,  38.5378,  51.9789,  73.4213,  26.7817,  38.9176,
                            52.0396,  73.8799,  26.9560,  39.0136,  52.1945,  73.9616,  26.8308,
                            39.0510,  52.0251,  74.0179,  26.8661,  39.1529,  52.0861,  74.0659,
                            26.9259,  39.1458,  52.1484,  74.0266,  27.0366,  39.2176,  52.2356,
                            74.0168],
                          [ 16.1232,  41.1759,  56.9170, 111.0000,  22.4535,  30.3435,  63.2190,
                            104.7747,  22.4145,  29.7438,  63.1723, 104.5728,  22.3309,  25.5902,
                            63.1183, 100.2271,  22.3318,  41.1798,  63.2164, 111.0000,  22.3281,
                            29.9716,  63.3524, 104.4641,  22.2027,  29.1093,  63.1380, 103.5586,
                            22.2202,  29.4885,  63.2728, 104.1961,  22.3218,  29.3094,  63.3146,
                            104.1250,  16.3824,  40.9787,  57.3955, 111.0000,  22.3916,  29.8769,
                            63.4797, 104.8680,  16.6448,  30.0338,  57.6683, 104.8085,  16.4266,
                            29.6302,  57.6806, 104.2014,  16.2811,  29.6128,  57.4799, 104.6626,
                            16.3323,  25.7212,  57.4461, 100.7091,  16.5149,  30.0998,  57.7212,
                            104.7926]]).cuda()
        scores = torch.Tensor([[0.7495],
                               [0.7391],
                               [0.6810]]).cuda()
        
        keep_idx_i = nms_gpu(torch.cat((t, scores), 1),0.7).type_as(scores)
        keep_idx_i = keep_idx_i.long().view(-1)
        print('keep_idx_i :',keep_idx_i.cpu().numpy(),keep_idx_i.nelement())

