#!/usr/bin/env python
"""
This analyzes imitate observe behavioural data.It could be generalized
to analyze any rapid event-related design experiment fairly easily.

Usage:
    dm-proc-imob.py [options] <project> <tmppath> <script> <assets>

Arguments:
    <project>           Full path to the project directory containing data/.
    <tmppath>           Full path to a shared folder to run
    <script>            Full path to an epitome-style script.
    <assets>            Full path to an assets folder containing
                                              EA-timing.csv, EA-vid-lengths.csv.

Options:
    -v,--verbose             Verbose logging
    --debug                  Debug logging

DETAILS

    1) Preprocesses MRI data.
    2) Produces an AFNI-compatible GLM file with the event timing.
    3) Runs the GLM analysis at the single-subject level.

    Each subject is run through this pipeline if the outputs do not already exist.

DEPENDENCIES

    + python
    + matlab
    + afni
    + fsl
    + epitome

    Requires dm-proc-freesurfer.py to be completed.

This message is printed with the -h, --help flags.
"""

from datman.docopt import docopt
from glob import glob
from random import choice
from string import ascii_uppercase, digits
import datman as dm
import logging
import os
import sys
import tempfile

logging.basicConfig(level=logging.WARN, 
        format="[%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(os.path.basename(__file__))

def process_functional_data(sub, data_path, log_path, tmp_path, tmpdict, script):

    nii_path = os.path.join(data_path, 'nii')
    t1_path = os.path.join(data_path, 't1')
    imob_path = os.path.join(data_path, 'imob')

    # check if already complete
    if os.path.isfile('{}/{}_preproc-complete.log'.format(imob_path, sub)) == True:
        logger.info('Subject {} has already been preprocessed.'.format(sub))
        raise ValueError

    # find freesurfer data
    t1_data = '{path}/{sub}_T1.nii.gz'.format(path=t1_path, sub=sub)
    aparc = '{path}/{sub}_APARC.nii.gz'.format(path=t1_path, sub=sub)
    aparc2009 = '{path}/{sub}_APARC2009.nii.gz'.format(path=t1_path, sub=sub)

    if not os.path.exists(t1_data):  
        logger.info('No T1 found for sub {}. Skipping.'.format(sub))
        raise ValueError

    if not os.path.exists(aparc):  
        logger.info('No aparc atlas found for sub {}. Skipping.'.format(sub))
        raise ValueError

    if not os.path.exists(aparc2009):  
        logger.info('No aparc 2009 atlas found for sub {}. Skipping.'.format(sub))
        raise ValueError

    ## find functional data
    # IMI
    IM_data = glob('{path}/{sub}/*_IMI_*.nii.gz'.format(path=nii_path, sub=sub))
    if not IM_data: 
        logger.error('No IMI data for sub {}. Skipping.'.format(sub))
        raise ValueError

    IM_data = IM_data[-1]   # if multiple, use one... 
    logger.debug('For sub {}, using IMI data: {}'.format(sub, IM_data))

    # OBS
    OB_data = glob('{path}/{sub}/*_OBS_*.nii.gz'.format(path=nii_path, sub=sub))
    if not OB_data: 
        logger.error('No OBS data for sub {}. Skipping.'.format(sub))
        raise ValueError

    OB_data = OB_data[-1]   # if multiple, use one... 
    logger.debug('For sub {}, using OBS data: {}'.format(sub, OB_data))

    try:
        tmpfolder = tempfile.mkdtemp(prefix='imob-', dir=tmp_path)
        tmpdict[sub] = tmpfolder
        dm.utils.make_epitome_folders(tmpfolder, 2)

        returncode, _, _ = dm.utils.run('cp {}/{} {}/TEMP/SUBJ/T1/SESS01/anat_T1_brain.nii.gz'.format(t1_path, t1_data, tmpfolder))
        dm.utils.check_returncode(returncode)
        returncode, _, _ = dm.utils.run('cp {}/{} {}/TEMP/SUBJ/T1/SESS01/anat_aparc_brain.nii.gz'.format(t1_path, aparc, tmpfolder))
        dm.utils.check_returncode(returncode)
        returncode, _, _ = dm.utils.run('cp {}/{} {}/TEMP/SUBJ/T1/SESS01/anat_aparc2009_brain.nii.gz'.format(t1_path, aparc2009, tmpfolder))
        dm.utils.check_returncode(returncode)
        returncode, _, _ = dm.utils.run('cp {}/{}/{} {}/TEMP/SUBJ/FUNC/SESS01/RUN01/FUNC01.nii.gz'.format(nii_path, sub, IM_data, tmpfolder))
        dm.utils.check_returncode(returncode)
        returncode, _, _ = dm.utils.run('cp {}/{}/{} {}/TEMP/SUBJ/FUNC/SESS01/RUN02/FUNC02.nii.gz'.format(nii_path, sub, OB_data, tmpfolder))
        dm.utils.check_returncode(returncode)

        # submit to queue
        uid = ''.join(choice(ascii_uppercase + digits) for _ in range(6))
        cmd = '{} {} 4 '.format(script, tmpfolder)
        name = 'dm_imob_{}_{}'.format(sub, uid)
        log = os.path.join(log_path, name + '.log')
        opts = 'h_vmem=3G,mem_free=3G,virtual_free=3G'

        cmd = 'qsub -o {log} -V -cwd -N {name} -l {opts} -j y {cmd}'.format(cmd=cmd, log=log, name=name, opts=opts)
        logger.debug('Running command: {}'.format(cmd))
        dm.utils.run(cmd)

        return name, tmpdict
    except:
        logger.exception("Error while preparing and running preprocessing job")
        raise ValueError

def export_data(sub, tmpfolder, func_path):

    tmppath = os.path.join(tmpfolder, 'TEMP', 'SUBJ', 'FUNC', 'SESS01')

    try:
        # make directory
        out_path = dm.utils.define_folder(os.path.join(func_path, sub))

        # export data
        dm.utils.run('cp {tmppath}/func_MNI-nonlin.DATMAN.01.nii.gz {out_path}/{sub}_func_MNI-nonlin.IM.01.nii.gz'.format(tmppath=tmppath, out_path=out_path, sub=sub))
        dm.utils.run('cp {tmppath}/func_MNI-nonlin.DATMAN.02.nii.gz {out_path}/{sub}_func_MNI-nonlin.OB.02.nii.gz'.format(tmppath=tmppath, out_path=out_path, sub=sub))
        dm.utils.run('cp {tmppath}/anat_EPI_mask_MNI-nonlin.nii.gz {out_path}/{sub}_anat_EPI_mask_MNI.nii.gz'.format(tmppath=tmppath, out_path=out_path, sub=sub))
        dm.utils.run('cp {tmppath}/reg_T1_to_TAL.nii.gz {out_path}/{sub}_reg_T1_to_MNI-lin.nii.gz'.format(tmppath=tmppath, out_path=out_path, sub=sub))
        dm.utils.run('cp {tmppath}/reg_nlin_TAL.nii.gz {out_path}/{sub}_reg_nlin_MNI.nii.gz'.format(tmppath=tmppath, out_path=out_path, sub=sub))

        # check outputs
        outputs = ('nonlin.IM.01', 'nonlin.OB.02', 'nlin_MNI', 'MNI-lin', 'mask_MNI')
        for out in outputs:
            if len(filter(lambda x: out in x, os.listdir(out_path))) == 0:
                logger.error('Failed to export {}'.format(out))
                raise ValueError

        dm.utils.run('cat {tmppath}/PARAMS/motion.DATMAN.01.1D > {out_path}/{sub}_motion.1D'.format(tmppath=tmppath, out_path=out_path, sub=sub))
        dm.utils.run('cat {tmppath}/PARAMS/motion.DATMAN.02.1D >> {out_path}/{sub}_motion.1D'.format(tmppath=tmppath, out_path=out_path, sub=sub))

        if os.path.isfile('{out_path}/{sub}_motion.1D'.format(out_path=out_path, sub=sub)) == False:
            logger.error('Failed to export {}_motion.1D'.format(sub))
            raise ValueError

        dm.utils.run('touch {out_path}/{sub}_preproc-complete.log'.format(out_path=out_path, sub=sub))
        dm.utils.run('rm -r {}'.format(tmpfolder))

    except:
        raise ValueError

    #TODO
    # os.system('cp {}/FUNC/SESS01/qc_reg_EPI_to_T1.pdf ' +
    #              '{}/imob/{}_qc_reg_EPI_to_T1.pdf'.format(
    #                                                     epidir, datadir, sub))
    # os.system('cp {}/FUNC/SESS01/qc_reg_T1_to_MNI.pdf ' +
    #              '{}/imob/{}_qc_reg_T1_to_MNI.pdf'.format(
    #                                                     epidir, datadir, sub))


def generate_analysis_script(sub, func_path, assets):
    """
    This writes the analysis script to replicate the methods in [insert paper
    here]. It expects timing files to exist (these are static, and are generated
    by 'imob-parse.py').

    Briefly, this is a standard rapid-event related design. We use 5 tent
    functions to explain each event over a 15 second window (this is the
    standard length of the HRF).

    Returns the path to the script that was generated or None if there was an
    error. 
    """
    # first, determine input functional files
    IM_data = glob('{path}/{sub}/*.IM.*.nii.gz')
    OB_data = glob('{path}/{sub}/*.OB.*.nii.gz')
    if not IM_data or OB_data: 
        logger.error("Missing IM or OB imob data for sub {}. Skipping.".format(sub))
        return None

    IM_data = IM_data[0]
    OB_data = OB_data[0]

    # open up the master script, write common variables
    script = '{func_path}/{sub}/{sub}_glm_1stlevel_cmd.sh'.format(func_path=func_path, sub=sub)

    f = open(script, 'wb')
    f.write("""#!/bin/bash

#
# Contrasts: emotional faces vs. fixation, emotional faces vs. neutral faces.
# use the 'bucket' dataset (*_1stlevel.nii.gz) for group level analysis.
#

# Imitate GLM for {sub}.
3dDeconvolve \\
    -input {IM_data} \\
    -mask {func_path}/{sub}/{sub}_anat_EPI_mask_MNI.nii.gz \\
    -ortvec {func_path}/{sub}/{sub}_motion.1D motion_paramaters \\
    -polort 4 \\
    -num_stimts 6 \\
    -local_times \\
    -jobs 8 \\
    -x1D {func_path}/{sub}/{sub}_glm_IM_1stlevel_design.mat \\
    -stim_label 1 IM_AN -stim_times 1 {assets}/IM_event-times_AN.1D \'BLOCK(1,1)\' \\
    -stim_label 2 IM_FE -stim_times 2 {assets}/IM_event-times_FE.1D \'BLOCK(1,1)\' \\
    -stim_label 3 IM_FX -stim_times 3 {assets}/IM_event-times_FX.1D \'BLOCK(1,1)\' \\
    -stim_label 4 IM_HA -stim_times 4 {assets}/IM_event-times_HA.1D \'BLOCK(1,1)\' \\
    -stim_label 5 IM_NE -stim_times 5 {assets}/IM_event-times_NE.1D \'BLOCK(1,1)\' \\
    -stim_label 6 IM_SA -stim_times 6 {assets}/IM_event-times_SA.1D \'BLOCK(1,1)\' \\
    -gltsym 'SYM: -1*IM_FX +0*IM_NE +0.25*IM_AN +0.25*IM_FE +0.25*IM_HA +0.25*IM_SA' \\
    -glt_label 1 emot-fix \\
    -gltsym 'SYM: +0*IM_FX -1*IM_NE +0.25*IM_AN +0.25*IM_FE +0.25*IM_HA +0.25*IM_SA' \\
    -glt_label 2 emot-neut \\
    -fitts   {func_path}/{sub}/{sub}_glm_IM_1stlvl_explained.nii.gz \\
    -errts   {func_path}/{sub}/{sub}_glm_IM_1stlvl_residuals.nii.gz \\
    -bucket  {func_path}/{sub}/{sub}_glm_IM_1stlvl.nii.gz \\
    -cbucket {func_path}/{sub}/{sub}_glm_IM_1stlvl_allcoeffs.nii.gz \\
    -fout -tout -xjpeg {func_path}/{sub}/{sub}_glm_IM_1stlevel_design.jpg

# Obserse GLM for {sub}.
3dDeconvolve \\
    -input {OB_data} \\
    -mask {func_path}/{sub}/{sub}_anat_EPI_mask_MNI.nii.gz \\
    -ortvec {func_path}/{sub}/{sub}_motion.1D motion_paramaters \\
    -polort 4 \\
    -num_stimts 6 \\
    -local_times \\
    -jobs 8 \\
    -x1D {func_path}/{sub}/{sub}_glm_OB_1stlevel_design.mat \\
    -stim_label 1 OB_AN -stim_times 1 {assets}/OB_event-times_AN.1D \'BLOCK(1,1)\' \\
    -stim_label 2 OB_FE -stim_times 2 {assets}/OB_event-times_FE.1D \'BLOCK(1,1)\' \\
    -stim_label 3 OB_FX -stim_times 3 {assets}/OB_event-times_FX.1D \'BLOCK(1,1)\' \\
    -stim_label 4 OB_HA -stim_times 4 {assets}/OB_event-times_HA.1D \'BLOCK(1,1)\' \\
    -stim_label 5 OB_NE -stim_times 5 {assets}/OB_event-times_NE.1D \'BLOCK(1,1)\' \\
    -stim_label 6 OB_SA -stim_times 6 {assets}/OB_event-times_SA.1D \'BLOCK(1,1)\' \\
    -gltsym 'SYM: -1*OB_FX +0*OB_NE +0.25*OB_AN +0.25*OB_FE +0.25*OB_HA +0.25*OB_SA' \\
    -glt_label 1 emot-fix \\
    -gltsym 'SYM: +0*OB_FX -1*OB_NE +0.25*OB_AN +0.25*OB_FE +0.25*OB_HA +0.25*OB_SA' \\
    -glt_label 2 emot-neut \\
    -fitts   {func_path}/{sub}/{sub}_glm_OB_1stlvl_explained.nii.gz \\
    -errts   {func_path}/{sub}/{sub}_glm_OB_1stlvl_residuals.nii.gz \\
    -bucket  {func_path}/{sub}/{sub}_glm_OB_1stlvl.nii.gz \\
    -cbucket {func_path}/{sub}/{sub}_glm_OB_1stlvl_allcoeffs.nii.gz \\
    -fout -tout -xjpeg {func_path}/{sub}/{sub}_glm_OB_1stlevel_design.jpg

""".format(IM_data=IM_data, OB_data=OB_data, func_path=func_path, assets=assets, sub=sub))
    f.close()

    return script

def main():
    """
    Loops through subjects, preprocessing using supplied script, and runs a
    first-level GLM using AFNI (tent functions, 15 s window) on all subjects.
    """
    arguments  = docopt(__doc__)
    project    = arguments['<project>']
    tmp_path   = arguments['<tmppath>']
    script     = arguments['<script>']
    assets     = arguments['<assets>']
    verbose    = arguments['--verbose']
    debug      = arguments['--debug']

    if verbose: 
        logger.setLevel(logging.INFO)
    if debug: 
        logger.setLevel(logging.DEBUG)

    data_path = dm.utils.define_folder(os.path.join(project, 'data'))
    nii_path = dm.utils.define_folder(os.path.join(data_path, 'nii'))
    func_path = dm.utils.define_folder(os.path.join(data_path, 'imob'))
    tmp_path = dm.utils.define_folder(tmp_path)
    _ = dm.utils.define_folder(os.path.join(project, 'logs'))
    log_path = dm.utils.define_folder(os.path.join(project, 'logs/imob'))

    list_of_names = []
    tmpdict = {}
    subjects = dm.utils.get_subjects(nii_path)

    # preprocess

    for sub in subjects:
        if dm.scanid.is_phantom(sub) == True:
            logger.debug("Skipping phantom subject {}".format(sub))
            continue
        if os.path.isfile(os.path.join(func_path, '{sub}/{sub}_preproc-complete.log'.format(sub=sub))) == True:
            continue
        try:
            logger.info("Preprocessing subject {}".format(sub))
            name, tmpdict = process_functional_data(sub, data_path, log_path, tmp_path, tmpdict, script)
            list_of_names.append(name)

        except ValueError as ve:
            continue

    if len(list_of_names) > 0:
        dm.utils.run_dummy_q(list_of_names)

    # export
    for sub in tmpdict:
        if os.path.isfile(os.path.join(func_path, '{sub}/{sub}_preproc-complete.log'.format(sub=sub))) == True:
            continue
        try:
            logger.info("Exporting subject {}".format(sub))
            export_data(sub, tmpdict[sub], func_path)
        except:
            logger.error('Failed to export {}'.format(sub))
            continue
        else:
            continue

    # analyze
    for sub in subjects:
        if dm.scanid.is_phantom(sub) == True:
            continue
        if os.path.isfile(os.path.join(func_path, '{sub}/{sub}_analysis-complete.log'.format(sub=sub))) == True:
            continue
        try:
            logger.info("Analyzing subject {}".format(sub))
            script = generate_analysis_script(sub, func_path, assets)
            if script: 
                returncode, _, _ = dm.utils.run('bash {}'.format(script))
                dm.utils.check_returncode(returncode)
                dm.utils.run('touch {func_path}/{sub}/{sub}_analysis-complete.log'.format(func_path=func_path, sub=sub))
        except Exception, e:
            logger.exception('Failed to analyze IMOB data for {}.'.format(sub))

if __name__ == "__main__":
    main()
