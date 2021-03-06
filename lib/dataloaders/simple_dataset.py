import torch
import torch.utils.data as data
from PIL import Image
import numpy as np
import os
import functools
import glob
import json
from lib.utils.create_tubes_from_boxes import create_tube_numpy as create_tube
from lib.utils.resize_rpn import resize_rpn_np

from lib.utils.spatial_transforms import (Compose, Normalize, Scale, ToTensor)
from lib.utils.temporal_transforms import LoopPadding

np.random.seed(42) #

def pil_loader(path):
    # open path as file to avoid ResourceWarning (https://github.com/python-pillow/Pillow/issues/835)
    with open(path, 'rb') as f:
        with Image.open(f) as img:
            return img.convert('RGB')


def accimage_loader(path):
    try:
        return accimage.Image(path)
    except IOError:
        # Potentially a decoding problem, fall back to PIL.Image
        return pil_loader(path)


def get_default_image_loader():
    from torchvision import get_image_backend
    if get_image_backend() == 'accimage':
        return accimage_loader
    else:
        return pil_loader


def video_loader(video_dir_path, frame_indices, image_loader):
    video = []
    for i in frame_indices:
        # image_path = os.path.join(video_dir_path, 'image_{:05d}.jpg'.format(i))
        # image_path = os.path.join(video_dir_path, '{:05d}.jpg'.format(i))
        image_path = os.path.join(video_dir_path, '{:05d}.png'.format(i))
        if os.path.exists(image_path):
            video.append(image_loader(image_path))
        else:
            print('image_path {} doesn\'t exist'.format( image_path))
            return video

    return video


def get_default_video_loader():
    image_loader = get_default_image_loader()
    return functools.partial(video_loader, image_loader=image_loader)


def load_annotation_data(data_file_path):
    with open(data_file_path, 'r') as data_file:
        return json.load(data_file)


def get_class_labels(data):
    class_labels_map = {}
    index = 0
    for class_label in data['labels']:
        class_labels_map[class_label] = index
        index += 1
    return class_labels_map


def get_video_names_and_annotations(data, subset):
    video_names = []
    annotations = []

    for key, value in data['database'].items():
        this_subset = value['subset']
        if this_subset == subset:
            if subset == 'testing':
                video_names.append('test/{}'.format(key))
            else:
                label = value['annotations']['label']
                video_names.append('{}/{}'.format(label, key))
                annotations.append(value['annotations'])

    return video_names, annotations

def create_tcn_dataset(split_txt_path,json_path, classes, mode):

    videos = []
    dataset = []
    txt_files = glob.glob(split_txt_path+'/*1.txt') # 1rst split
    for txt in txt_files:
        class_name = txt.split('/')[-1][:-16]
        class_idx = classes.index(class_name)
        with open(txt, 'r') as fp:
            lines=fp.readlines()
        for l in lines:
            spl = l.split()
            if spl[1] == '1' and mode == 'train': # train video
                vid_name = spl[0][:-4]
                videos.append(vid_name)
            elif spl[1] == '2' and( mode == 'test' or mode == 'val'): # train video
                vid_name = spl[0][:-4]
                videos.append(vid_name)

        with open(os.path.join(json_path,class_name+'.json'), 'r') as fp:
            data = json.load(fp)
        for feat in data.keys():
            if feat in videos:
                sample = {
                    'video' : feat,
                    'class' : class_name,
                    'class_idx' : class_idx
                }
                dataset.append(sample)
    print(len(dataset))

    return dataset
    
def make_dataset(dataset_path, split_txt_path, boxes_file, mode='train'):
    dataset = []
    classes = next(os.walk(dataset_path, True))[1]

    with open(boxes_file, 'r') as fp:
        boxes_data = json.load(fp)
        
    assert classes != (None), 'classes must not be None, Check dataset path'
    
    max_sim_actions = -1
    max_frames = -1
    for idx, cls in enumerate(classes):
        
        class_path = os.path.join(dataset_path, cls)
        videos = []
        with open(os.path.join(split_txt_path,'{}_test_split1.txt'.format(cls)), 'r') as fp:
            lines=fp.readlines()
        for l in lines:
            spl = l.split()
            if spl[1] == '1' and mode == 'train' : # train video
                vid_name = spl[0][:-4]
                b_key =  os.path.join(cls,vid_name)
                if b_key in boxes_data:
                    videos.append(vid_name)
                else:
                    print ( '2', b_key)
            elif spl[1] == '2' and (mode == 'test' or mode == 'val'): # train video
                vid_name = spl[0][:-4]

                videos.append(vid_name)

        # # for each video
        # videos =  next(os.walk(class_path,True))[1]
        for vid in videos:

            video_path = os.path.join(dataset_path, cls, vid)
            n_frames = len(glob.glob(video_path+'/*.png'))
            begin_t = 1

            if n_frames > max_frames :
                max_frames = n_frames
            json_key = os.path.join(cls,vid)
            boxes = boxes_data[json_key]
            end_t = min(n_frames,len(boxes))

            video_sample = {
                'video': vid,
                'class': cls,
                'abs_path' : video_path,
                'begin_t' : begin_t,
                'end_t' : end_t,
                'boxes' : boxes
            }

            dataset.append(video_sample)
    print(len(dataset))
    print('max_time_dim :',max_frames)
    return dataset, max_frames


class Video(data.Dataset):
    def __init__(self, video_path, frames_dur=8, split_txt_path=None, sample_size= 112,
                 spatial_transform=None, temporal_transform=None, json_file = None,
                 sample_duration=16, get_loader=get_default_video_loader, mode='train', classes_idx=None):

        self.mode = mode
        self.data, max_frames = make_dataset(video_path, split_txt_path, json_file, self.mode)
        self.spatial_transform = spatial_transform
        self.temporal_transform = temporal_transform
        self.loader = get_loader()
        self.sample_duration = frames_dur
        self.sample_size = sample_size
        self.json_file = json_file
        self.classes_idx = classes_idx

        self.max_time_dim = len(range(0,max_frames-self.sample_duration, int(self.sample_duration/2)))
        print(list(range(0,max_frames-self.sample_duration, int(self.sample_duration/2))))
        print('self.max_time_dim :',self.max_time_dim)
        
    def __getitem__(self, index):
        """
        Args:
            index (int): Index
        Returns:
            tuple: (image, target) where target is class_index of the target class.
        """
        # print(self.data[index]['video'])
        
        path = self.data[index]['abs_path']
        begin_t = self.data[index]['begin_t']
        end_t = self.data[index]['end_t']
        boxes = self.data[index]['boxes']

        # print('boxes :',boxes)

        boxes_np = np.array(boxes, dtype=float)
        # print('path :',path, 'index :', index)
        
        n_frames = self.data[index]['end_t']
        if n_frames < 17:
            print('n_frames :',n_frames)

        frame_indices= list(
            range( begin_t, end_t+1))

        if self.temporal_transform is not None:
            frame_indices = self.temporal_transform(frame_indices)
        clip = self.loader(path, frame_indices)

        # # get original height and width
        w, h = clip[0].size
        
        # print('boxes_np.shape :',boxes_np.shape)
        boxes_np[:,0] = np.clip(boxes_np[:,0], 0, w)
        boxes_np[:,1] = np.clip(boxes_np[:,1], 0, h)
        boxes_np[:,2] = np.clip(boxes_np[:,2], 0, w)
        boxes_np[:,3] = np.clip(boxes_np[:,3], 0, h)

        cls = self.data[index]['class']
        boxes_r = resize_rpn_np(boxes_np, h,w, self.sample_size)
        # print('cls :',cls)
        class_int = self.classes_idx[cls]
        # print('class_int  :',class_int )
        target = class_int

        if self.spatial_transform is not None:
            clip = [self.spatial_transform(img) for img in clip]
        clip = torch.stack(clip, 0)
        # print('index is :',index)
        # print('self.max_time_dim :',self.max_time_dim)
        clips = torch.zeros((self.max_time_dim,3,self.sample_duration,self.sample_size,self.sample_size)) # contains all the clips
        tmp_clip = torch.zeros(( self.sample_duration, 3,self.sample_size, self.sample_size))           # copy each clip before permute
        # print('before clips.shape :',clips.shape)
        gt_tubes = np.zeros((self.max_time_dim,1,7))
        gt_rois = np.zeros((self.max_time_dim,self.sample_duration,5))

        labels = np.array([[class_int]] * boxes_r.shape[0])
        if n_frames < 17:
            indexes = [0]
        else:
            indexes = range(0, (n_frames -self.sample_duration  ), int(self.sample_duration/2))
        for i in indexes :
            lim = min(i+self.sample_duration-1, (n_frames-1))
            vid_indices = np.arange(i,lim+1)
            
            # print(len(vid_indices))
            # print('vid_indices :',vid_indices)
            # print('clip.shape :',clip.shape)
            # print('vid_indices.shape[0] :',vid_indices.shape[0] )
            # print('clip[vid_indices].shape :',clip[vid_indices].shape)
            # print('tmp_clip[:lim+1].shape :',tmp_clip[:len(vid_indices)].shape)
            tmp_clip[:len(vid_indices)] = clip[vid_indices]
            # print('tmp_clip.shape :',tmp_clip.shape)
            clips[int(i/self.sample_duration*2)] = tmp_clip.permute(1,0,2,3)

            ## create tubes
            # print('boxes_r.shape[0] :',boxes_r.shape)
            gt_rois_seg = np.concatenate( (boxes_r[ vid_indices], labels[vid_indices]),axis=1)
            # print('gt_rois_seg.shape :',gt_rois_seg.shape)
            # print('gt_rois.shape :',gt_rois.shape)
            gt_rois[int(i/self.sample_duration*2), :gt_rois_seg.shape[0]] = gt_rois_seg
            # print('boxes_np :',boxes_np)
            # print('boxes_r :',boxes_r)
            gt_tubes_seg = create_tube(np.expand_dims(np.expand_dims(gt_rois_seg,0),0),np.array([[self.sample_size,self.sample_size]]), self.sample_duration)
            # print('gt_tubes_seg :',gt_tubes_seg)
            gt_tubes_seg[:,:,2] = i
            gt_tubes_seg[:,:,5] = lim
            # print('gt_tubes_seg:',gt_tubes_seg.shape)
            gt_tubes[int(i/self.sample_duration*2),0] = gt_tubes_seg

        # print('gt_tubes :',gt_tubes)
        # print('clips.shape :',clips.shape)
        im_info = torch.Tensor([[self.sample_size, self.sample_size, n_frames] ]*self.max_time_dim )
        if self.mode == 'train':
            return clips, (h,w), target, gt_tubes, im_info, n_frames
        elif self.mode == 'val':
            return clips, (h,w), target, gt_tubes, im_info, n_frames
        else:
            return clips, (h,w), target, gt_tubes, im_info, n_frames, self.data[index]['abs_path'], frame_indices
        
        
    def __len__(self):
        return len(self.data)

if __name__ == "__main__":

    classes = ['brush_hair', 'clap', 'golf', 'kick_ball', 'pour',
               'push', 'shoot_ball', 'shoot_gun', 'stand', 'throw', 'wave',
               'catch','climb_stairs', 'jump', 'pick', 'pullup', 'run', 'shoot_bow', 'sit',
               'swing_baseball', 'walk'
               ]
    cls2idx = { classes[i] : i for i in range(0, len(classes)) }


    dataset_folder = '/gpu-data2/sgal/JHMDB-act-detector-frames'
    splt_txt_path =  '/gpu-data2/sgal/splits'
    boxes_file = '/gpu-data2/sgal/poses.json'
    sample_size = 112
    sample_duration = 16 #len(images)

    batch_size = 1
    n_threads = 0
    
    mean = [103.29825354, 104.63845484,  90.79830328] # jhmdb from .png

    spatial_transform = Compose([Scale(sample_size), # [Resize(sample_size),
                                 # CenterCrop(sample_size),
                                 ToTensor(),
                                 Normalize(mean, [1, 1, 1])])
    temporal_transform = LoopPadding(sample_duration)

    data = Video(dataset_folder, frames_dur=sample_duration, spatial_transform=spatial_transform,
                 temporal_transform=temporal_transform, json_file = boxes_file,
                 split_txt_path=splt_txt_path, mode='train', classes_idx=cls2idx)
    data_loader = torch.utils.data.DataLoader(data, batch_size=batch_size,
                                              shuffle=False, num_workers=n_threads, pin_memory=True)
    # clips, (h,w), gt_tubes, gt_bboxes, n_actions, n_frames = next(data_loader.__iter__())
    # for i in data:
    #     clips, (h,w), gt_tubes, gt_bboxes, n_actions, n_frames = i
    #     # print('gt_bboxes.shape :',gt_bboxes)
    #     # print('gt_bboxes.shape :',gt_bboxes.shape)
    #     # print('gt_tubes :',gt_tubes)
    #     # print('clips.shape :',clips.shape)

    #     # print('n_frames :',n_frames)
    #     if (n_frames != gt_bboxes.size(1)):
    #         print('probleeeemm', ' n_frames :',n_frames, ' gt_bboxes :',gt_bboxes.size(1))
    # clips, (h,w), target, gt_tubes,   n_frames = data[166] # 14 frames
    clips, (h,w), target, gt_tubes, im_info,  n_frames = data[14]
    # if (n_frames != gt_bboxes.size(1)):
    #     print('probleeeemm', ' n_frames :',n_frames, ' gt_bboxes :',gt_bboxes.size(1))
    print('clips.shape :',clips.shape)
    print('gt_tubes :',gt_tubes)
    print('gt_tubes :',gt_tubes.shape)
    # print('gt_bboxes :',gt_bboxes)
    # print('gt_bboxes :',gt_bboxes.shape)
    
    print('n_frames :',n_frames)
