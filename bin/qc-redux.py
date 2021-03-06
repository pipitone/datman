#!/usr/bin/env python
"""
Produces QC documents for each exam.

Usage:
    qc_redux.py [options] <file.nii.gz> <qcpath>

Arguments:
    <file.nii.gz>        Scan ID to QC for. E.g. DTI_CMH_H001_01_01
    <qcpath>             Path to the qc files

Options:
    --scantype <tag>          The type of scan to QC
    --checkheaderlogs <path>  Read check header log files
    --bvecstandards <path>    Compare .bval and .bvec to gold standards
    --verbose                 Be chatty
    --debug                   Be extra chatty
    --dry-run                 Don't actually do any work

DETAILS

    This program requires the AFNI toolkit to be available, as well as NIFTI
    scans for each acquisition to be QC'd. That is, it searches for exported
    nifti acquistions in:

        <datadir>/nifti/<timepoint>

    The database stores some of the numbers plotted here, and is used by web-
    build to generate interactive charts detailing the acquisitions over time.
"""
import os
import sys
import glob
import sqlite3
import datetime
import numpy as np
import scipy as sp
import scipy.signal as sig
import dicom as dcm
import nibabel as nib
import datman as dm
import datman.utils
import datman.scanid
import subprocess as proc
from copy import copy
from docopt import docopt
import tempfile

import matplotlib
matplotlib.use('Agg')   # Force matplotlib to not use any Xwindows backend
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

DEBUG  = False
VERBOSE= False
DRYRUN = False

###############################################################################
# HELPERS

def log(message):
    print message
    sys.stdout.flush()

def error(message):
    log("ERROR: " + message)

def verbose(message):
    if not(VERBOSE or DEBUG): return
    log(message)

def debug(message):
    if not DEBUG: return
    log("DEBUG: " + message)

def makedirs(path):
    debug("makedirs: {}".format(path))
    if not DRYRUN: os.makedirs(path)

def run(cmd):
    debug("exec: {}".format(cmd))
    if not DRYRUN:
        p = proc.Popen(cmd, shell=True, stdout=proc.PIPE, stderr=proc.PIPE)
        out, err = p.communicate()
        if p.returncode != 0:
            log("Error {} while executing: {}".format(p.returncode, cmd))
            out and log("stdout: \n>\t{}".format(out.replace('\n','\n>\t')))
            err and log("stderr: \n>\t{}".format(err.replace('\n','\n>\t')))
        else:
            debug("rtnval: {}".format(p.returncode))
            out and debug("stdout: \n>\t{}".format(out.replace('\n','\n>\t')))
            err and debug("stderr: \n>\t{}".format(err.replace('\n','\n>\t')))

def add_pic_to_html(qchtml, pic):
    '''
    Adds a pic to an html page with this handler "qchtml"
    '''
    relpath = os.path.relpath(pic,qcpath)
    qchtml.write('<a href="'+ relpath + '" style="color: #99CCFF" >')
    qchtml.write('<img src="' + relpath + '" "WIDTH=800" > ')
    qchtml.write(relpath + '</a><br>\n')
    return qchtml

def create_db(cur):
    cur.execute('CREATE TABLE fmri (subj TEXT, site TEXT)')
    cur.execute('CREATE TABLE dti (subj TEXT, site TEXT)')
    cur.execute('CREATE TABLE t1 (subj TEXT, site TEXT)')

def insert_value(cur, table, subj, colname, value):
    """
    Insets values into the database (differently for numeric and string data).
    """

    # check if column exits, add if it does not
    cur.execute('PRAGMA table_info({})'.format(table))
    d = cur.fetchall()

    cols = []
    for col in d:
        cols.append(str(col[1]))

    if colname not in cols:
        cur.execute('ALTER TABLE {table} ADD COLUMN {colname} FLOAT DEFAULT null'.format(
                           table=table, colname=colname))

    # check if subject exists
    cur.execute("""SELECT * FROM {table} WHERE subj='{subj}'""".format(
                       table=table, subj=subj))
    d = cur.fetchall()

    # if subject does not exist, insert row
    if len(d) == 0:
        if type(value) == str:
            cur.execute("""INSERT INTO {table}(subj, {colname}) VALUES('{subj}', '{value}')""".format(
                           table=table, subj=subj, colname=colname, value=value))
        else:
            cur.execute("""INSERT INTO {table}(subj, {colname}) VALUES('{subj}', {value})""".format(
                           table=table, subj=subj, colname=colname, value=value))
    # otherwise, update row
    else:
        if type(value) == str:
            cur.execute("""UPDATE {table} SET {colname} = '{value}' WHERE subj='{subj}'""".format(
                           table=table, subj=subj, colname=colname, value=value))
        else:
            cur.execute("""UPDATE {table} SET {colname} = {value} WHERE subj='{subj}'""".format(
                           table=table, subj=subj, colname=colname, value=value))


def factors(n):
    """
    Returns all factors of n.
    """
    return set(reduce(list.__add__,
                ([i, n//i] for i in range(1, int(n**0.5) + 1) if n % i == 0)))

def square_factors(fac, num):
    """
    Finds the two most square factors of a number from a list of factors.
    Factors returned with the smallest first.
    """
    candidates = []
    for x in fac:
        for y in fac:
            if x*y == num:
                candidates.append(abs(x-y))
    most_square = np.min(candidates)
    for x in fac:
        for y in fac:
            if x*y == num:
                if x-y == most_square:
                    factor = [x, y]
    if factor[0] > factor[1]:
        factor = factor[::-1]

    return factor

def load_masked_data(func, mask):
    """
    Accepts 'functional.nii.gz' and 'mask.nii.gz', and returns a voxels x
    timepoints matrix of the functional data in non-zero mask locations.
    """
    func = nib.load(func).get_data()
    mask = nib.load(mask).get_data()

    mask = mask.reshape(mask.shape[0]*mask.shape[1]*mask.shape[2])
    func = func.reshape(func.shape[0]*func.shape[1]*func.shape[2],
                                                    func.shape[3])

    # find within-brain timeseries
    idx = np.where(mask > 0)[0]
    func = func[idx, :]

    return func

def check_n_trs(fpath):
    """
    Returns the number of TRs for an input file. If the file is 3D, we also
    return 1.
    """
    data = nib.load(fpath)

    try:
        ntrs = data.shape[3]
    except:
        ntrs = 1

    return ntrs

def bounding_box(filename):
    """
    Finds a box that only includes all nonzero voxels in a 3D image. Output box
    is represented as 3 x 2 numpy array with rows denoting x, y, z, and columns
    denoting stand and end slices.

    Usage:
        box = bounding_box(filename)
    """

    # find 3D bounding box
    box = np.zeros((3,2))  # init bounding box
    flag = 0  # ascending

    for i, dim in enumerate(filename.shape): # loop through (x, y, z)

        # ascending search
        while flag == 0:
            for dim_test in np.arange(dim):

                # get sum of all values in each slice
                if i == 0:   test = np.sum(filename[dim_test, :, :])
                elif i == 1: test = np.sum(filename[:, dim_test, :])
                elif i == 2: test = np.sum(filename[:, :, dim_test])

                # if slice is nonzero, set starting bound, switch to descending
                if test >= 1:
                    box[i, 0] = dim_test
                    flag = 1
                    break

        # descending search
        while flag == 1:
            for dim_test in np.arange(dim):

                dim_test = dim-dim_test - 1  # we have to reverse things

                # get sum of all values in each slice
                if i == 0:   test = np.sum(filename[dim_test, :, :])
                elif i == 1: test = np.sum(filename[:, dim_test, :])
                elif i == 2: test = np.sum(filename[:, :, dim_test])

                # if slice is nonzero, set ending bound, switch to ascending
                if test >= 1:
                    box[i, 1] = dim_test
                    flag = 0
                    break

    return box

def reorient_4d_image(image):
    """
    Reorients the data to radiological, one TR at a time
    """
    for i in np.arange(image.shape[3]):

        if i == 0:
            newimage = np.transpose(image[:, :, :, i], (2,0,1))
            newimage = np.rot90(newimage, 2)

        elif i == 1:
            tmpimage = np.transpose(image[:, :, :, i], (2,0,1))
            tmpimage = np.rot90(tmpimage, 2)
            newimage = np.concatenate((newimage[...,np.newaxis],
                                       tmpimage[...,np.newaxis]), axis=3)

        else:
            tmpimage = np.transpose(image[:, :, :, i], (2,0,1))
            tmpimage = np.rot90(tmpimage, 2)
            newimage = np.concatenate((newimage,
                                       tmpimage[...,np.newaxis]), axis=3)

    image = copy(newimage)

    return image

###############################################################################
# PLOTTERS / CALCULATORS

def montage(image, name, filename, qchtml, cmaptype='grey', mode='3d', minval=None, maxval=None, box=None):
    """
    Creates a montage of images displaying a image set on top of a grayscale
    image.

    Generally, this will be used to plot an image (of type 'name') that was
    generated from the original file 'filename'. So if we had an SNR map
    'SNR.nii.gz' from 'fMRI.nii.gz', we would submit everything to montage
    as so:

        montage('SNR.nii.gz', 'SNR', 'EPI.nii.gz', pdf)

    Usage:
        montage(image, name, filename, pdf)

        image    -- submitted image file name
        name     -- name of the printout (e.g, SNR map, t-stats, etc.)
        cmaptype -- 'redblue', 'hot', or 'gray'.
        minval   -- colormap minimum value as a % (None == 'auto')
        maxval   -- colormap maximum value as a % (None == 'auto')
        mode     -- '3d' (prints through space) or '4d' (prints through time)
        filename -- qc image file name
        png      -- png object to save the figure to
        box      -- a (3,2) tuple that describes the start and end voxel
                    for x, y, and z, respectively. If None, we find it ourselves.
    """
    image = str(image) # input checks
    opath = os.path.dirname(image) # grab the image folder
    output = str(image)
    image = nib.load(image).get_data() # load in the daterbytes
    basefpath = os.path.basename(image)
    stem = basefpath.replace('nii.gz','')
    pic = os.path.join(qcpath,stem + '.png')

    if mode == '3d':
        if len(image.shape) > 3: # if image is 4D, only keep the first time-point
            image = image[:, :, :, 0]

        image = np.transpose(image, (2,0,1))
        image = np.rot90(image, 2)
        steps = np.round(np.linspace(0,np.shape(image)[0]-2, 36)) # coronal plane
        factor = 6

        # use bounding box (submitted or found) to crop extra-brain regions
        if box == None:
            box = bounding_box(image) # get the image bounds
        elif box.shape != (3,2): # if we did, ensure it is the right shape
            error('ERROR: Bounding box should have shape = (3,2).')
            raise ValueError
        image = image[box[0,0]:box[0,1], box[1,0]:box[1,1], box[2,0]:box[2,1]]

    if mode == '4d':
        image = reorient_4d_image(image)
        midslice = np.floor((image.shape[2]-1)/2) # print a single plane across all slices
        factor = np.ceil(np.sqrt(image.shape[3])) # print all timepoints
        factor = factor.astype(int)

    # colormapping -- set value
    if cmaptype == 'redblue': cmap = plt.cm.RdBu_r
    elif cmaptype == 'hot': cmap = plt.cm.OrRd
    elif cmaptype == 'gray': cmap = plt.cm.gray
    else:
        debug('No valid colormap supplied, default = greyscale.')
        cmap = plt.cm.gray

    # colormapping -- set range
    if minval == None:
        minval = np.min(image)
    else:
        minval = np.min(image) + ((np.max(image) - np.min(image)) * minval)

    if maxval == None:
        maxval = np.max(image)
    else:
        maxval = np.max(image) * maxval

    cmap.set_bad('g', 0)  # value for transparent pixels in the overlay

    fig, axes = plt.subplots(nrows=factor, ncols=factor, facecolor='white')
    for i, ax in enumerate(axes.flat):

        if mode == '3d':
            im = ax.imshow(image[steps[i], :, :], cmap=cmap, interpolation='nearest', vmin=minval, vmax=maxval)
            ax.set_frame_on(False)
            ax.axes.get_xaxis().set_visible(False)
            ax.axes.get_yaxis().set_visible(False)

        elif mode == '4d' and i < image.shape[3]:
            im = ax.imshow(image[:, :, midslice, i], cmap=cmap, interpolation='nearest')
            ax.set_frame_on(False)
            ax.axes.get_xaxis().set_visible(False)
            ax.axes.get_yaxis().set_visible(False)

        elif mode == '4d' and i >= image.shape[3]:
            ax.set_axis_off() # removes extra axes from plot

    fig.subplots_adjust(right=0.8)
    cbar_ax = fig.add_axes([0.85, 0.15, 0.05, 0.7])
    cb = fig.colorbar(im, cax=cbar_ax)
    #cb.set_label(name, labelpad=0, y=0.5)
    fig.suptitle(filename + '\n' + name, size=10)

    fig.savefig(pic, format='png')
    plt.close()

    ## add the plot to the qchtml
    qchtml = add_pic_to_html(qchtml, pic)

    return qchtml

    def find_epi_spikes(image, filename, qchtml, ftype, cur=None, bvec=None):

        """
        Plots, for each axial slice, the mean instensity over all TRs.
        Strong deviations are an indication of the presence of spike
        noise.

        If bvec is supplied, we remove all time points that are 0 in the bvec
        vector.

        Usage:
            find_epi_spikes(image, filename, pdf)

            image    -- submitted image file name
            filename -- qc image file name
            pdf      -- PDF object to save the figure to
            ftype     -- 'fmri' or 'dti'
            cur      -- cursor object for subject qc database (if None, don't use)
            bvec     -- numpy array of bvecs (for finding direction = 0)

        """

        image = str(image)             # input checks
        opath = os.path.dirname(image) # grab the image folder
        pic = os.path.join(qcpath,filename + '_fmriplots.png')

        # load in the daterbytes
        output = str(image)
        image = nib.load(image).get_data()
        image = reorient_4d_image(image)

        x = image.shape[1]
        y = image.shape[2]
        z = image.shape[0]
        t = image.shape[3]

        # initialize the spikecount
        spikecount = 0

        # find the most square set of factors for n_trs
        factor = np.ceil(np.sqrt(z))
        factor = factor.astype(int)

        fig, axes = plt.subplots(nrows=factor, ncols=factor, facecolor='white')

        # sets the bounds of the image
        c1 = np.round(x*0.25)
        c2 = np.round(x*0.75)

        # for each axial slice
        for i, ax in enumerate(axes.flat):
            if i < z:

                v_mean = np.array([])
                v_sd = np.array([])

                # find the mean, STD, of each dir and concatenate w. vector
                for j in np.arange(t):

                    # gives us a subset of the image
                    sample = image[i, c1:c2, c1:c2, j]
                    mean = np.mean(sample)
                    sd = np.std(sample)

                    if j == 0:
                        v_mean = copy(mean)
                        v_sd = copy(sd)
                    else:
                        v_mean = np.hstack((v_mean, mean))
                        v_sd = np.hstack((v_sd, sd))

                # crop out b0 images
                if bvec == None:
                    v_t = np.arange(t)
                else:
                    idx = np.where(bvec != 0)[0]
                    v_mean = v_mean[idx]
                    v_sd = v_sd[idx]
                    v_t = np.arange(len(idx))

                # keep track of spikes
                v_spikes = np.where(v_mean > np.mean(v_mean)+np.mean(v_sd))[0]
                spikecount = spikecount + len(v_spikes)

                ax.plot(v_mean, color='black')
                ax.fill_between(v_t, v_mean-v_sd, v_mean+v_sd, alpha=0.5, color='black')
                ax.set_frame_on(False)
                ax.axes.get_xaxis().set_visible(False)
                ax.axes.get_yaxis().set_visible(False)
            else:
                ax.set_axis_off()

        if cur:
            subj = filename.split('_')[0:4]
            subj = '_'.join(subj)

            insert_value(cur, ftype, subj, 'spikecount', spikecount)

        plt.suptitle(filename + '\n' + 'DTI Slice/TR Wise Abnormalities', size=10)
        plt.savefig(pic, format='png')
        plt.close()
        qchtml = add_pic_to_html(qchtml, pic)
        return qchtml

    def fmri_plots(func, mask, f, filename, qchtml, cur=None):
        """
        Calculates and plots:
             + Mean and SD of normalized spectra across brain.
             + Framewise displacement (mm/TR) of head motion.
             + Mean correlation from 10% of the in-brain voxels.
             + EMPTY ADD KEWL PLOT HERE PLZ.

        """

        pic = os.path.join(qcpath,filename + '_fmriplots.png')
        ##############################################################################
        # spectra
        plt.subplot(2,2,1)
        func = load_masked_data(func, mask)
        spec = sig.detrend(func, type='linear')
        spec = sig.periodogram(spec, fs=0.5, return_onesided=True, scaling='density')
        freq = spec[0]
        spec = spec[1]
        sd = np.nanstd(spec, axis=0)
        mean = np.nanmean(spec, axis=0)

        plt.plot(freq, mean, color='black', linewidth=2)
        plt.plot(freq, mean + sd, color='black', linestyle='-.', linewidth=0.5)
        plt.plot(freq, mean - sd, color='black', linestyle='-.', linewidth=0.5)
        plt.title('Whole-brain spectra mean, SD', size=6)
        plt.xticks(size=6)
        plt.yticks(size=6)
        plt.xlabel('Frequency (Hz)', size=6)
        plt.ylabel('Power', size=6)
        plt.xticks([])

        ##############################################################################
        # framewise displacement
        plt.subplot(2,2,2)
        fd_thresh = 0.5
        f = np.genfromtxt(f)
        f[:,0] = np.radians(f[:,0]) * 50 # 50 = head radius, need not be constant.
        f[:,1] = np.radians(f[:,1]) * 50 # 50 = head radius, need not be constant.
        f[:,2] = np.radians(f[:,2]) * 50 # 50 = head radius, need not be constant.
        f = np.abs(np.diff(f, n=1, axis=0))
        f = np.sum(f, axis=1)
        t = np.arange(len(f))

        plt.plot(t, f.T, lw=1, color='black')
        plt.axhline(y=fd_thresh, xmin=0, xmax=len(t), color='r')
        plt.xlim((-3, len(t) + 3)) # this is in TRs
        plt.ylim(0, 2) # this is in mm/TRs
        plt.xticks(size=6)
        plt.yticks(size=6)
        plt.xlabel('TR', size=6)
        plt.ylabel('Framewise displacement (mm/TR)', size=6)
        plt.title('Head motion', size=6)

        if cur:
            fdtot = np.sum(f) # total framewise displacement
            fdnum = len(np.where(f > fd_thresh)[0]) # number of TRs above 0.5 mm FD

            subj = filename.split('_')[0:4]
            subj = '_'.join(subj)

            insert_value(cur, 'fmri', subj, 'fdtot', fdtot)
            insert_value(cur, 'fmri', subj, 'fdnum', fdnum)

        ##############################################################################
        # whole brain correlation
        plt.subplot(2,2,3)
        idx = np.random.choice(func.shape[0], func.shape[0]/10, replace=False)
        corr = func[idx, :]
        corr = sp.corrcoef(corr, rowvar=1)
        mean = np.mean(corr, axis=None)
        std = np.std(corr, axis=None)

        im = plt.imshow(corr, cmap=plt.cm.RdBu_r, interpolation='nearest', vmin=-1, vmax=1)
        plt.xlabel('Voxel', size=6)
        plt.ylabel('Voxel', size=6)
        plt.xticks([])
        plt.yticks([])
        cb = plt.colorbar(im)
        cb.set_label('Correlation (r)', labelpad=0, y=0.5, size=6)
        for tick in cb.ax.get_yticklabels():
            tick.set_fontsize(6)
        plt.title('Whole-brain r mean={}, SD={}'.format(str(mean), str(std)), size=6)

        if cur:
            subj = filename.split('_')[0:4]
            subj = '_'.join(subj)

            insert_value(cur, 'fmri', subj, 'corrmean', mean)
            insert_value(cur, 'fmri', subj, 'corrsd', std)

        ##############################################################################
        # add a final plot?
        plt.suptitle(filename)
        plt.savefig(pic, format='png')
        plt.close()

        qchtml = add_pic_to_html(qchtml, pic)
        return qchtml


def add_slicer_pic(fpath,slicergap,picwidth,qchtml):
    """
    Uses FSL's slicer function to generate a pretty montage png from a nifty file
    Then adds a link to that png in the qcthml

    Usage:
        add_slicer_pic(fpath,slicergap,picwidth,qchtml)

        fpath       -- submitted image file name
        slicergap   -- int of "gap" between slices in Montage
        picwidth    -- width (in pixels) of output image
        qchtml      -- file handle for qc html page to link to
    """
    ### figure out a name for the output image from the input file name
    basefpath = os.path.basename(fpath)
    stem = basefpath.replace('nii.gz','')
    pic = os.path.join(qcpath,stem + '.png')
    ## make the pic using FSL's slicer function
    run("slicer {} -S {} {} {}".format(fpath,slicergap,picwidth,pic))
    ## add pic to html
    qchtml = add_pic_to_html(qchtml, pic)

def add_headercompare_note(headerlog, fpath, qchtml):
    """
    Reads the header log and prints any errors related to this particular scan to the qchtml
    Usage:
        add_headercompare_note(headerlog,fpath,qchtml)

        headerlog   -- full path to log file from checkheaders
        fpath       -- submitted image file name
        qchtml      -- file handle for qc html page to link to
    """
    basefpath = os.path.basename(fpath)
    stem = basefpath.replace('nii.gz','')
    if CHECKHEADERS:
        for line in open(headerlog).readlines():
            if re.match(stem, line):
                qchtml.write("<p>{}</p>".format(line))

###############################################################################
# PIPELINES

def ignore(fpath, qchtml, cur):
    pass

def fmri_qc(fpath, qchtml, cur):
    """
    This takes an input image, motion corrects, and generates a brain mask.
    It then calculates a signal to noise ratio map and framewise displacement
    plot for the file.
    """
    # if the number of TRs is too little, we skip the pipeline
    ntrs = check_n_trs(fpath)

    if ntrs < 20:
        qchtml.write("<p>This is a truncated scan. Number of TRs: {}</p>".format(ntrs))
        return qchtml

    ## check the header
    add_headercompare_note(headerlog, fpath, qchtml)

    filename = os.path.basename(fpath)
    tmpdir = tempfile.mkdtemp(prefix='qc-')

    run('3dvolreg \
         -prefix {t}/mcorr.nii.gz \
         -twopass -twoblur 3 -Fourier \
         -1Dfile {t}/motion.1D {f}'.format(t=tmpdir, f=fpath))
    run('3dTstat -prefix {t}/mean.nii.gz {t}/mcorr.nii.gz'.format(t=tmpdir))
    run('3dAutomask \
         -prefix {t}/mask.nii.gz \
         -clfrac 0.5 -peels 3 {t}/mean.nii.gz'.format(t=tmpdir))
    run('3dTstat -prefix {t}/std.nii.gz  -stdev {t}/mcorr.nii.gz'.format(t=tmpdir))
    run("""3dcalc \
           -prefix {t}/sfnr.nii.gz \
           -a {t}/mean.nii.gz -b {t}/std.nii.gz -expr 'a/b'""".format(t=tmpdir))

    qchtml = montage(fpath, 'BOLD-contrast', filename, qchtml, maxval=0.75)
    qchtml = fmri_plots('{t}/mcorr.nii.gz'.format(t=tmpdir),
                     '{t}/mask.nii.gz'.format(t=tmpdir),
                     '{t}/motion.1D'.format(t=tmpdir), filename, qchtml)
    qchtml = montage('{t}/sfnr.nii.gz'.format(t=tmpdir),
                  'SFNR', filename, qchtml, cmaptype='hot', maxval=0.75)
    qchtml = find_epi_spikes(fpath, filename, qchtml, 'fmri')

    run('rm -r {}'.format(tmpdir))

    return qchtml

def rest_qc(fpath, qchtml, cur):
    """
    This takes an input image, motion corrects, and generates a brain mask.
    It then calculates a signal to noise ratio map and framewise displacement
    plot for the file.

    At the moment, the only difference between this and fmri_qc is that this
    also adds some stats to the subject-qc database.
    """
    # if the number of TRs is too little, we skip the pipeline
    qchtml = fmri_qc(fpath, qchtml, cur)

    return qchtml

def emp_qc(fpath, qchtml, cur):
    '''
    Run qc for an the empathic accuracy task
    It's the same as fmri_qc except that it also checks that the behavioural files exist
    '''
    # if the number of TRs is too little, we skip the pipeline
    qchtml = fmri_qc(fpath, qchtml, cur)
    ## also need to check that the behavioural files in this task are in the onsets

def t1_qc(fpath, qchtml, cur):
    ## slicer pic
    add_slicer_pic(fpath,qcpath,5,1600,qchtml)
    ## check header compare
    add_headercompare_note(headerlog, fpath, qchtml)
    return qchtml

def pd_qc(fpath, qchtml, cur):
    ## slicer pic
    add_slicer_pic(fpath,qcpath,2,1600,qchtml)
    return qchtml

def t2_qc(fpath, qchtml, cur):
    ## slicer pic
    add_slicer_pic(fpath,qcpath,2,1600,qchtml)
    return qchtml

def flair_qc(fpath, qchtml, cur):
    ## slicer pic
    add_slicer_pic(fpath,qcpath,5,1600,qchtml)
    ## check header compare
    add_headercompare_note(headerlog, fpath, qchtml)
    return qchtml

def dti_qc(fpath, qchtml, cur):
    """
    Runs the QC pipeline on the DTI inputs. We use the BVEC (not BVAL)
    file to find B0 images (in some scans, mid-sequence B0s are coded
    as non-B0s for some reason, so the 0-direction locations in BVEC
    seem to be the safer choice).
    """
    filename = os.path.basename(fpath)
    directory = os.path.dirname(fpath)

    add_headercompare_note(headerlog, fpath, qchtml)

    ### also need to add bval bvec compare

    # load in bvec file
    bvec = filename.split('.')
    try:
        bvec.remove('gz')
    except:
        pass
    try:
        bvec.remove('nii')
    except:
        pass

    bvec = np.genfromtxt(os.path.join(directory, ".".join(bvec) + '.bvec'))
    bvec = np.sum(bvec, axis=0)

    qchtml = montage(fpath, 'B0-contrast', filename, qchtml, maxval=0.25)
    qchtml = montage(fpath, 'DTI Directions', filename, qchtml, mode='4d', maxval=0.25)
    qchtml = find_epi_spikes(fpath, filename, qchtml, 'dti', cur=cur, bvec=bvec)

    return qchtml

####################################################################
def main():
    """
    This spits out our QCed data
    """
    global VERBOSE
    global DEBUG
    global DRYRUN

    arguments   = docopt(__doc__)
    fpath       = arguments['<file.nii.gz>']
    qcpath      = arguments['<qcpath>']
    scantype    = arguments['--scantype']
    hdcmplogs   = arguments['--checkheaderlogs']
    bvec_std    = arguments['--bvecstandards']
    VERBOSE     = arguments['--verbose']
    DEBUG       = arguments['--debug']
    DRYRUN      = arguments['--dry-run']

    QC_HANDLERS = {   # map from tag to QC function
            "T1"            : t1_qc,
            "T2"            : t2_qc,
            "PD"            : pd_qc,
            "PDT2"          : ignore,
            "FLAIR"         : flair_qc,
            "FMAP"          : ignore,
            "FMAP-6.5"      : ignore,
            "FMAP-8.5"      : ignore,
            "RST"           : rest_qc,
            "SPRL"          : rest_qc,
            "OBS"           : fmri_qc,
            "IMI"           : fmri_qc,
            "NBK"           : fmri_qc,
            "EMP"           : emp_qc,
            "fMRI"          : fmri_qc,
            "DTI"           : dti_qc,
            "DTI60-29-1000" : dti_qc,
            "DTI60-20-1000" : dti_qc,
            "DTI60-1000"    : dti_qc,
            "DTI60-b1000"   : dti_qc,
            "DTI33-1000"    : dti_qc,
            "DTI33-b1000"   : dti_qc,
            "DTI33-3000"    : dti_qc,
            "DTI33-b3000"   : dti_qc,
            "DTI33-4500"    : dti_qc,
            "DTI33-b4500"   : dti_qc,
    }

    ## check that the input nii.gz file exists
    if not os.path.isfile(fpath):
        sys.exit('Cannot find input {}'.format(fpath))

    ## make qc directory (if it doesnot exits)
    qcdir = dm.utils.define_folder(qcpath)
    qchtml = open(os.path.join(qcdir,'qc.html'),'a')

    ## define headerlog if needed
    if hdcmplogs != None:
        if not os.path.exists(hdcmplogs):
            sys.exit('Cannot find headerlogs directory {}'.format(fpath))
    ## define bvec and bval standards if needed

    ## get file type and send off the qc
    verbose("QC scan {}".format(fname))
    if scantype = None:
        for tag in QC_HANDLERS.keys():
            if tag in os.path.basename(fpath):
                QC_HANDLERS[tag](fname, qchtml, cur)
                break
        else:
            sys.exit("Could not find scantype for {}, exiting".format(fpath))
    else:
        if scantype not in QC_HANDLERS:
            sys.exit("Scantype {} not in list, exiting".format(scantype))
        else:
            QC_HANDLERS[scantype](fname, qchtml, cur)

        continue


    qchtml.close()

if __name__ == "__main__":
    main()
