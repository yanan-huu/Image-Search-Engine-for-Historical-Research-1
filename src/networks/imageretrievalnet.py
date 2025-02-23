import os
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.utils.model_zoo as model_zoo
import pandas as pd
import torchvision

from src.layers.pooling import MAC, SPoC, GeM, GeMmp, RMAC, Rpool
from src.layers.normalization import L2N, PowerLaw
from src.datasets.genericdataset import ImagesFromList
from src.utils.general import get_data_root, path_all_jpg, save_path_feature
from src.datasets.datahelpers import pil_loader, imresize
from src.networks.networks import ResNetSOAs


PRETRAINED = {
        'rSfM120k-tl-resnet50-gem-w'  : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/retrieval-SfM-120k/rSfM120k-tl-resnet50-gem-w-97bf910.pth',
        'rSfM120k-tl-resnet101-gem-w' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/retrieval-SfM-120k/rSfM120k-tl-resnet101-gem-w-a155e54.pth',
        'rSfM120k-tl-resnet152-gem-w' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/retrieval-SfM-120k/rSfM120k-tl-resnet152-gem-w-f39cada.pth',
        'gl18-tl-resnet50-gem-w'      : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/gl18/gl18-tl-resnet50-gem-w-83fdc30.pth',
        'gl18-tl-resnet101-gem-w'     : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/gl18/gl18-tl-resnet101-gem-w-a4d43db.pth',
        'gl18-tl-resnet152-gem-w'     : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/gl18/gl18-tl-resnet152-gem-w-21278d5.pth',
        'UResNet101'                  : 'data/networks/uresnet101-normals.pth.tar',
}

# for some models, we have imported features (convolutions) from caffe because the image retrieval performance is higher for them
FEATURES = {
    'vgg16'     : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/imagenet/imagenet-caffe-vgg16-features-d369c8e.pth',
    'resnet50'  : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/imagenet/imagenet-caffe-resnet50-features-ac468af.pth',
    'resnet101' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/imagenet/imagenet-caffe-resnet101-features-10a101d.pth',
    'resnet152' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/networks/imagenet/imagenet-caffe-resnet152-features-1011020.pth',
}

# TODO: pre-compute for more architectures and properly test variations (pre l2norm, post l2norm)
# pre-computed local pca whitening that can be applied before the pooling layer
L_WHITENING = {
    'resnet101' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-lwhiten-9f830ef.pth', # no pre l2 norm
    # 'resnet101' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-lwhiten-da5c935.pth', # with pre l2 norm
}

# possible global pooling layers, each on of these can be made regional
POOLING = {
    'mac'   : MAC,
    'spoc'  : SPoC,
    'gem'   : GeM,
    'gemmp' : GeMmp,
    'rmac'  : RMAC,
}

# TODO: pre-compute for: resnet50-gem-r, resnet50-mac-r, vgg16-mac-r, alexnet-mac-r
# pre-computed regional whitening, for most commonly used architectures and pooling methods
R_WHITENING = {
    'alexnet-gem-r'   : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-alexnet-gem-r-rwhiten-c8cf7e2.pth',
    'vgg16-gem-r'     : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-vgg16-gem-r-rwhiten-19b204e.pth',
    'resnet101-mac-r' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-mac-r-rwhiten-7f1ed8c.pth',
    'resnet101-gem-r' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-gem-r-rwhiten-adace84.pth',
}

# TODO: pre-compute for more architectures
# pre-computed final (global) whitening, for most commonly used architectures and pooling methods
WHITENING = {
    'alexnet-gem'     : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-alexnet-gem-whiten-454ad53.pth',
    'alexnet-gem-r'   : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-alexnet-gem-r-whiten-4c9126b.pth',
    'vgg16-gem'       : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-vgg16-gem-whiten-eaa6695.pth',
    'vgg16-gem-r'     : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-vgg16-gem-r-whiten-83582df.pth',
    'resnet50-gem'    : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet50-gem-whiten-f15da7b.pth',
    'resnet101-mac-r' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-mac-r-whiten-9df41d3.pth',
    'resnet101-gem'   : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-gem-whiten-22ab0c1.pth',
#    'resnet101-gem'  : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/gl18/gl18-50perlid-resnet101-gem-whiten-0ea46be.pth',
    'resnet101-gem-r' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-gem-r-whiten-b379c0a.pth',
    'resnet101-gemmp' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet101-gemmp-whiten-770f53c.pth',
    'resnet152-gem'   : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-resnet152-gem-whiten-abe7b93.pth',
    'densenet121-gem' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-densenet121-gem-whiten-79e3eea.pth',
    'densenet169-gem' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-densenet169-gem-whiten-6b2a76a.pth',
    'densenet201-gem' : 'http://cmp.felk.cvut.cz/cnnimageretrieval/data/whiten/retrieval-SfM-120k/retrieval-SfM-120k-densenet201-gem-whiten-22ea45c.pth',
}

# output dimensionality for supported architectures
OUTPUT_DIM = {
    'alexnet'       :  256,
    'vgg11'         :  512,
    'vgg13'         :  512,
    'vgg16'         :  512,
    'vgg19'         :  512,
    'resnet18'      :  512,
    'resnet34'      :  512,
    'resnet50'      : 2048,
    'resnet101'     : 2048,
    'resnet152'     : 2048,
    'densenet121'   : 1024,
    'densenet169'   : 1664,
    'densenet201'   : 1920,
    'densenet161'   : 2208, # largest densenet
    'squeezenet1_0' :  512,
    'squeezenet1_1' :  512,
}

class ImageRetrievalNet(nn.Module):
    
    def __init__(self, features, lwhiten, pool, whiten, meta):
        super(ImageRetrievalNet, self).__init__()
        self.features = nn.Sequential(*features)
        self.lwhiten = lwhiten
        self.pool = pool
        self.whiten = whiten
        self.norm = L2N()
        self.meta = meta
    
    def forward(self, x):
        # x -> features
        o = self.features(x)

        # TODO: properly test (with pre-l2norm and/or post-l2norm)
        # if lwhiten exist: features -> local whiten
        if self.lwhiten is not None:
            # o = self.norm(o)
            s = o.size()
            o = o.permute(0,2,3,1).contiguous().view(-1, s[1])
            o = self.lwhiten(o)
            o = o.view(s[0],s[2],s[3],self.lwhiten.out_features).permute(0,3,1,2)
            # o = self.norm(o)

        # features -> pool -> norm
        o = self.norm(self.pool(o)).squeeze(-1).squeeze(-1)

        # if whiten exist: pooled features -> whiten -> norm
        if self.whiten is not None:
            o = self.norm(self.whiten(o))

        # permute so that it is Dx1 column vector per image (DxN if many images)
        return o.permute(1,0)

    def __repr__(self):
        tmpstr = super(ImageRetrievalNet, self).__repr__()[:-1]
        tmpstr += self.meta_repr()
        tmpstr = tmpstr + ')'
        return tmpstr

    def meta_repr(self):
        tmpstr = '  (' + 'meta' + '): dict( \n' # + self.meta.__repr__() + '\n'
        tmpstr += '     architecture: {}\n'.format(self.meta['architecture'])
        tmpstr += '     local_whitening: {}\n'.format(self.meta['local_whitening'])
        tmpstr += '     pooling: {}\n'.format(self.meta['pooling'])
        tmpstr += '     regional: {}\n'.format(self.meta['regional'])
        tmpstr += '     whitening: {}\n'.format(self.meta['whitening'])
        tmpstr += '     outputdim: {}\n'.format(self.meta['outputdim'])
        tmpstr += '     mean: {}\n'.format(self.meta['mean'])
        tmpstr += '     std: {}\n'.format(self.meta['std'])
        tmpstr = tmpstr + '  )\n'
        return tmpstr



class SOLAR_Global_Retrieval(nn.Module):
    def __init__(self, architecture, features, lwhiten, pool, whiten, meta, mode='train', pretrained_type='gl18', soa_layers='45'):
        super(SOLAR_Global_Retrieval, self).__init__()
        self.features = ResNetSOAs(architecture, pretrained_type, soa_layers, mode)
        self.lwhiten = lwhiten
        self.pool = pool
        self.whiten = whiten
        self.norm = L2N()
        self.meta = meta
        self.mode = mode
        self.pool.mode = self.mode

    def forward(self, x):
        # x -> features
        o = self.features(x, self.mode)

        # TODO: properly test (with pre-l2norm and/or post-l2norm)
        # if lwhiten exist: features -> local whiten
        if self.lwhiten is not None:
            # o = self.norm(o)
            s = o.size()
            o = o.permute(0,2,3,1).contiguous().view(-1, s[1])
            o = self.lwhiten(o)
            o = o.view(s[0],s[2],s[3],self.lwhiten.out_features).permute(0,3,1,2)
            # o = self.norm(o)

        # features -> pool -> norm
        o = self.norm(self.pool(o)).squeeze(-1).squeeze(-1)

        # if whiten exist: pooled features -> whiten -> norm
        if self.whiten is not None:
            o = self.norm(self.whiten(o))

        # permute so that it is Dx1 column vector per image (DxN if many images)
        #return o.permute(1,0)

        # do not permute here for DataParallel, permute when gathered

        return o

    def __repr__(self):
        tmpstr = super(ImageRetrievalNet, self).__repr__()[:-1]
        tmpstr += self.meta_repr()
        tmpstr = tmpstr + ')'
        return tmpstr

    def meta_repr(self):
        tmpstr = '(' + 'meta' + '): dict( \n' # + self.meta.__repr__() + '\n'
        tmpstr += 'architecture: {}\n'.format(self.meta['architecture'])
        tmpstr += 'local_whitening: {}\n'.format(self.meta['local_whitening'])
        tmpstr += 'pooling: {}\n'.format(self.meta['pooling'])
        tmpstr += 'p: {}\n'.format(self.pool.p.data.item())
        tmpstr += 'regional: {}\n'.format(self.meta['regional'])
        tmpstr += 'whitening: {}\n'.format(self.meta['whitening'])
        tmpstr += 'outputdim: {}\n'.format(self.meta['outputdim'])
        tmpstr += 'mean: {}\n'.format(self.meta['mean'])
        tmpstr += 'std: {}\n'.format(self.meta['std'])
        tmpstr += 'soa: {}\n'.format(self.meta['soa'])
        tmpstr += 'soa_layers: {}\n'.format(self.meta['soa_layers'])
        tmpstr = tmpstr + '  )\n'
        return tmpstr


def init_network(params):

    # parse params with default values
    architecture = params.get('architecture', 'resnet101')
    local_whitening = params.get('local_whitening', False)
    pooling = params.get('pooling', 'gem')
    p = params.get('p', 3.)
    regional = params.get('regional', False)
    whitening = params.get('whitening', False)
    mean = params.get('mean', [0.485, 0.456, 0.406])
    std = params.get('std', [0.229, 0.224, 0.225])
    pretrained = params.get('pretrained', True)
    soa = params.get('soa', False)
    soa_layers = params.get('soa_layers', '45')
    pretrained_type = params.get('pretrained_type', 'SfM120k')
    flatten_desc = params.get('flatten_desc', False)
    mode = params.get('mode', 'train')

    # get output dimensionality size
    dim = OUTPUT_DIM[architecture]

    # loading network from torchvision
    if pretrained:
        if architecture not in FEATURES:
            # initialize with network pretrained on imagenet in pytorch
            net_in = getattr(torchvision.models, architecture)(pretrained=True)
        else:
            # initialize with random weights, later on we will fill features with custom pretrained network
            net_in = getattr(torchvision.models, architecture)(pretrained=False)
    else:
        # initialize with random weights
        net_in = getattr(torchvision.models, architecture)(pretrained=False)

    # initialize features
    # take only convolutions for features,
    # always ends with ReLU to make last activations non-negative
    if architecture.startswith('alexnet'):
        features = list(net_in.features.children())[:-1]
    elif architecture.startswith('vgg'):
        features = list(net_in.features.children())[:-1]
    elif architecture.startswith('resnet'):
        #feat0.weight.data = torch.nn.init.kaiming_normal_(feat0.weight.data)
        features = list(net_in.children())[:-2]
    elif architecture.startswith('densenet'):
        features = list(net_in.features.children())
        features.append(nn.ReLU(inplace=True))
    elif architecture.startswith('squeezenet'):
        features = list(net_in.features.children())
    else:
        raise ValueError('Unsupported or unknown architecture: {}!'.format(architecture))

    # initialize local whitening
    if local_whitening:
        lwhiten = nn.Linear(dim, dim, bias=True)
        # TODO: lwhiten with possible dimensionality reduce

        if pretrained:
            lw = architecture
            if lw in L_WHITENING:
                print(">> {}: for '{}' custom computed local whitening '{}' is used"
                    .format(os.path.basename(__file__), lw, os.path.basename(L_WHITENING[lw])))
                whiten_dir = os.path.join(get_data_root(), 'whiten')
                lwhiten.load_state_dict(model_zoo.load_url(L_WHITENING[lw], model_dir=whiten_dir))
            else:
                print(">> {}: for '{}' there is no local whitening computed, random weights are used"
                    .format(os.path.basename(__file__), lw))

    else:
        lwhiten = None

    # initialize pooling
    if pooling == 'gemmp':
        pool = POOLING[pooling](p=p, mp=dim)
    else:
        pool = POOLING[pooling](p=p)

    # initialize regional pooling
    if regional:
        rpool = pool
        rwhiten = nn.Linear(dim, dim, bias=True)
        # TODO: rwhiten with possible dimensionality reduce

        if pretrained:
            rw = '{}-{}-r'.format(architecture, pooling)
            if rw in R_WHITENING:
                print(">> {}: for '{}' custom computed regional whitening '{}' is used"
                    .format(os.path.basename(__file__), rw, os.path.basename(R_WHITENING[rw])))
                whiten_dir = os.path.join(get_data_root(), 'whiten')
                rwhiten.load_state_dict(model_zoo.load_url(R_WHITENING[rw], model_dir=whiten_dir))
            else:
                print(">> {}: for '{}' there is no regional whitening computed, random weights are used"
                    .format(os.path.basename(__file__), rw))

        pool = Rpool(rpool, rwhiten)

    # initialize whitening
    if whitening:
        whiten = nn.Linear(dim, dim, bias=True)
        # TODO: whiten with possible dimensionality reduce

        if pretrained:
            w = architecture
            if local_whitening:
                w += '-lw'
            w += '-' + pooling
            if regional:
                w += '-r'
            if w in WHITENING:
                print(">> {}: for '{}' custom computed whitening '{}' is used"
                    .format(os.path.basename(__file__), w, os.path.basename(WHITENING[w])))
                whiten_dir = os.path.join(get_data_root(), 'whiten')
                whiten.load_state_dict(model_zoo.load_url(WHITENING[w], model_dir=whiten_dir))
            else:
                print(">> {}: for '{}' there is no whitening computed, random weights are used"
                    .format(os.path.basename(__file__), w))
    else:
        whiten = None

    # create meta information to be stored in the network
    meta = {
        'architecture' : architecture,
        'local_whitening' : local_whitening,
        'pooling' : pooling,
        'regional' : regional,
        'whitening' : whitening,
        'mean' : mean,
        'std' : std,
        'outputdim' : dim,
        'soa': soa,
        'soa_layers': soa_layers,
    }

    # create a generic image retrieval network
    net = SOLAR_Global_Retrieval(architecture, features, lwhiten, pool, whiten, meta, pretrained_type=pretrained_type, soa_layers=soa_layers, mode=mode)

    return net

def extract_vectors(net, images, image_size, transform, bbxs=None, ms=[1], msp=1, print_freq=10, summary=None, mode='test'):
    # moving network to gpu and eval mode
    net.cuda()
    net.eval()

    # creating dataset loader
    loader = torch.utils.data.DataLoader(
            ImagesFromList(root='', images=images, imsize=image_size, bbxs=bbxs, transform=transform, mode=mode),
            batch_size=1, shuffle=False, num_workers=8, pin_memory=True
        )

    # extracting vectors
    with torch.no_grad():
        vecs = torch.zeros(net.meta['outputdim'], len(images))
        with tqdm(total=len(images)) as pbar:
            for i, _input in enumerate(loader):
                _input = _input.cuda()

                if len(ms) == 1 and ms[0] == 1:
                    vecs[:, i] = extract_ss(net, _input)
                else:
                    vecs[:, i] = extract_ms(net, _input, ms, msp)
                
                if (i+1) % print_freq == 0:
                    pbar.update(print_freq)
                elif (i+1) == len(images):
                    pbar.update(len(images) % print_freq)

    return vecs

def extract_vectors_single(net, image, image_size, transform, bbxs=None, ms=[1], msp=1):
    # moving network to gpu and eval mode
    net.cuda()
    net.eval()

    input = pil_loader(image)
    input = imresize(input, image_size)
    input = transform(input)
    input = torch.unsqueeze(input, 0)

    # extracting vectors
    with torch.no_grad():
        input = input.cuda()

        if len(ms) == 1 and ms[0] == 1:
            vec = extract_ss(net, input)
        else:
            vec = extract_ms(net, input, ms, msp)

    return vec

def extr_selfmade_dataset(net, selfmadedataset, image_size, transform, ms=[1], msp=1):
    if selfmadedataset == 'GLM/test':
        path_head = '/home/yuanyuanyao/data/test/GLM/'
        df = pd.read_csv(path_head + 'retrieval_solution_v2.1.csv', usecols= ['id','images'])
        df_filtered = df.loc[df['images'] != 'None']
        query_id = df_filtered['id'].tolist()
        images = [path_head+'test/'+id[0]+'/'+id[1]+'/'+id[2]+'/'+id+'.jpg' for id in query_id]
        img_r_path = [os.path.relpath(path, "/home/yuanyuanyao/data/") for path in images]
    else:
        folder_path = os.path.join('/home/yuanyuanyao/data/test', selfmadedataset)
        images, img_r_path = path_all_jpg(folder_path, start="/home/yuanyuanyao/data")
    # extract database vectors
    print('>> {}: images...'.format(selfmadedataset))
    vecs = extract_vectors(net, images, image_size, transform, ms=ms, msp=msp)
    # convert to numpy
    vecs = vecs.numpy()
    save_path_feature(selfmadedataset, vecs, img_r_path)

def extract_vectors_PQ(net, images, image_size, transform, bbxs=None, print_freq=10):
    # moving network to gpu and eval mode
    net.cuda()
    net.eval()

    # creating dataset loader
    loader = torch.utils.data.DataLoader(
        ImagesFromList(root='', images=images, imsize=image_size, bbxs=bbxs, transform=transform),
        batch_size=1, shuffle=False, num_workers=8, pin_memory=True
    )

    # extracting vectors
    with torch.no_grad():
        quantized_vecs = torch.zeros(net.meta['outputdim'], len(images))
        vecs = torch.zeros(net.meta['outputdim'], len(images))
        idx = torch.zeros(net.N_books, len(images))
        for i, input in enumerate(loader):
            input = input.cuda()

            quantized_vecs_temp, idx_temp, C_temp, vecs_temp = net(input)
            quantized_vecs[:, i] = quantized_vecs_temp.cpu().data.squeeze()
            vecs[:, i] = vecs_temp.cpu().data.squeeze()
            idx[:, i] = idx_temp.cpu().data.squeeze()

            if (i+1) % print_freq == 0 or (i+1) == len(images):
                print('\r>>>> {}/{} done...'.format((i+1), len(images)), end='')
        print('')
    C = C_temp.cpu().data.squeeze()

    return quantized_vecs, idx, C, vecs


def extract_ss(net, _input):
    return net(_input).cpu().data.squeeze()

def extract_ms(net, _input, ms, msp):

    v = torch.zeros(net.meta['outputdim'])

    for s in ms:
        if s == 1:
            _input_t = _input.clone()
        else:
            _input_t = nn.functional.interpolate(_input, scale_factor=s, mode='bilinear', align_corners=False)
        v += net(_input_t).pow(msp).cpu().data.squeeze()

    v /= len(ms)
    v = v.pow(1./msp)
    v /= v.norm()

    return v
