#!/usr/bin/env python
"""
This run freesurfer pipeline on T1 images.
Also now extracts some volumes and converts some files to nifty for epitome

Usage:
  dm-proc-freesurfer.py [options] <inputdir> <FS_subjectsdir>

Arguments:
    <inputdir>                Top directory for nii inputs normally (project/data/nii/)
    <FS_subjectsdir>          Top directory for the Freesurfer output

Options:
  --do-not-sink            Do not convert a data to nifty for epitome
  --T1-sinkdir PATH        Full path to the location of the 't1' (epitome) directory
  --no-postFS              Do not submit postprocessing script to the queue
  --postFS-only            Only run the post freesurfer analysis
  --T1-tag STR             Tag used to find the T1 files (default is 'T1')
  --tag2 STR               Optional tag used (as well as '--T1-tag') to filter for correct input
  --multiple-inputs        Allow multiple input T1 files to Freesurfersh
  --FS-option STR          A quoted string of an non-default freesurfer option to add.
  --run-version STR        A version string that is appended to 'run_freesurfer_<tag>.sh' for mutliple versions
  --QC-transfer QCFILE     QC checklist file - if this option is given than only QCed participants will be processed.
  --prefix STR             A prefix string (used by the ENIGMA Extract) to filter to subject ids.
  --use-test-datman        Use the version of datman in Erin's test environment. (default is '/archive/data-2.0/code/datman.module')
  -v,--verbose             Verbose logging
  --debug                  Debug logging in Erin's very verbose style
  -n,--dry-run             Dry run
  -h, --help               Show help

DETAILS
This run freesurfer pipeline on T1 images maps after conversion to nifty.
Also submits a dm-freesurfer-sink.py and some extraction scripts as a held job.

This script will look search inside the "inputdir" folder for T1 images to process.
If uses the '--T1-tag' string (which is '_T1_' by default) to do so.
If this optional argument (('--tag2') is given, this string will be used to refine
the search, if more than one T1 file is found inside the participants directory.

The T1 image found for each participant in printed in the 'T1_nii' column
of "freesurfer-checklist.csv". If no T1 image is found, or more than one T1 image
is found, a note to that effect is printed in the "notes" column of the same file.
You can manually overide this process by editing the "freesurfer-checklist.csv"
with the name of the T1 image you would like processed (esp. in the case of repeat scans).

The script then looks to see if any of the T1 images (listed in the
"freesurfer-checklist.csv" "T1_nii" column) have not been processed (i.e. have no outputs).
These images are then submitted to the queue.

If the "--QC-transfer" option is used, the QC checklist from data transfer
(i.e. metadata/checklist.csv) and only those participants who passed QC will be processed.

The '--run-version' option was added for situations when you might want to use
different freesurfer settings for a subgroup of your participants (for example,
all subjects from a site with an older scanner (but have all the
outputs show up in the same folder in the end). The run version string is appended
to the freesurfer_run.sh script name. Which allows for mutliple freesurfer_run.sh
scripts to exists in the bin folder.



Will load freesurfer in queue:
module load freesurfer/5.3.0
(also requires the datmat python enviroment)

Written by Erin W Dickie, Sep 30 2015
Adapted from old dm-proc-freesurfer.py
"""
from docopt import docopt
import pandas as pd
import datman as dm
import datman.utils
import datman.scanid
import glob
import os
import time
import sys
import subprocess
import datetime
import tempfile
import shutil
import filecmp
import difflib

arguments       = docopt(__doc__)
inputdir        = arguments['<inputdir>']
subjectsdir     = arguments['<FS_subjectsdir>']
rawQCfile       = arguments['--QC-transfer']
MULTI_T1        = arguments['--multiple-inputs']
NO_SINK         = arguments['--do-not-sink']
T1sinkdir       = arguments['--T1-sinkdir']
T1_tag          = arguments['--T1-tag']
TAG2            = arguments['--tag2']
RUN_TAG         = arguments['--run-version']
FS_option       = arguments['--FS-option']
prefix          = arguments['--prefix']
NO_POST         = arguments['--no-postFS']
POSTFS_ONLY     = arguments['--postFS-only']
TESTDATMAN      = arguments['--use-test-datman']
VERBOSE         = arguments['--verbose']
DEBUG           = arguments['--debug']
DRYRUN          = arguments['--dry-run']

if DEBUG: print arguments
#set default tag values
if T1_tag == None: T1_tag = '_T1_'
QCedTranfer = False if rawQCfile == None else True
USE_TAG2 = False if TAG2 == None else True # if tag2 is given, use it

## if T1 sink directory is not specified - put it in the default place
if T1sinkdir == None: T1sinkdir = os.path.join(os.path.dirname(subjectsdir),'t1')

## set the basenames of the two run scripts
if RUN_TAG == None:
    runFSsh_name = 'run_freesurfer.sh'
else:
    runFSsh_name = 'run_freesurfer_' + RUN_TAG + '.sh'
runPostsh_name = 'postfreesurfer.sh'

## two silly little things to find for the run script

### Erin's little function for running things in the shell
def docmd(cmdlist):
    "sends a command (inputed as a list) to the shell"
    if DEBUG: print ' '.join(cmdlist)
    if not DRYRUN: subprocess.call(cmdlist)

# need to find the t1 weighted scan and update the checklist
def find_T1images(archive_tag):
    """
    will look for new files in the inputdir
    and add them to a list for the processing

    archive_tag -- filename tag that can be used for search (i.e. '_T1_')
    checklist -- the checklist pandas dataframe to update
    """
    for i in range(0,len(checklist)):
        sdir = os.path.join(inputdir,checklist['id'][i])
	    #if T1 name not in checklist
        if pd.isnull(checklist['T1_nii'][i]):
            sfiles = []
            for fname in os.listdir(sdir):
                if archive_tag in fname:
                    sfiles.append(fname)

            if DEBUG: print "Found {} {} in {}".format(len(sfiles),archive_tag,sdir)
            if len(sfiles) == 1:
                checklist['T1_nii'][i] = sfiles[0]
            elif len(sfiles) > 1:
                if MULTI_T1:
                    '''
                    if multiple T1s are allowed (as per --multiple-inputs flag) - add to T1 file
                    '''
                    checklist['T1_nii'][i] = ';'.join(sfiles)
                else:
                    checklist['notes'][i] = "> 1 {} found".format(archive_tag)
            elif len(sfiles) < 1:
                checklist['notes'][i] = "No {} found.".format(archive_tag)


### build a template .sh file that gets submitted to the queue
def makeFreesurferrunsh(filename):
    """
    builds a script in the subjectsdir (run.sh)
    that gets submitted to the queue for each participant (in the case of 'doInd')
    or that gets held for all participants and submitted once they all end (the concatenating one)
    """
    bname = os.path.basename(filename)
    if bname == runFSsh_name:
        FS_STEP = 'FS'
    if bname == runPostsh_name:
        FS_STEP = 'Post'

    #open file for writing
    Freesurfersh = open(filename,'w')
    Freesurfersh.write('#!/bin/bash\n\n')

    Freesurfersh.write('# SGE Options\n')
    Freesurfersh.write('#$ -S /bin/bash\n')
    Freesurfersh.write('#$ -q main.q\n')
    Freesurfersh.write('#$ -j y \n')
    Freesurfersh.write('#$ -o '+ log_dir + ' \n')
    Freesurfersh.write('#$ -e '+ log_dir + ' \n')
    Freesurfersh.write('#$ -l mem_free=6G,virtual_free=6G\n\n')

    Freesurfersh.write('#source the module system\n')
    Freesurfersh.write('source /etc/profile\n\n')

    Freesurfersh.write('## this script was created by dm-proc-freesurfer.py\n\n')
    ## can add section here that loads chosen CIVET enviroment
    Freesurfersh.write('##load the Freesurfer enviroment\n')
    Freesurfersh.write('module load freesurfer/5.3.0\n\n')

    Freesurfersh.write('export SUBJECTS_DIR=' + subjectsdir + '\n\n')
    ## write the freesurfer running bit
    if FS_STEP == 'FS':

        Freesurfersh.write('SUBJECT=${1}\n')
        Freesurfersh.write('shift\n')
        Freesurfersh.write('T1MAPS=${@}\n')
        ## add the engima-dit command

        Freesurfersh.write('\nrecon-all -all ')
        if FS_option != None:
            Freesurfersh.write(FS_option + ' ')
        Freesurfersh.write('-subjid ${SUBJECT} ${T1MAPS}' + ' -qcache\n')

    ## write the post freesurfer bit
    if FS_STEP == 'Post':
        # The dm-freesurfer-sink.py bit requires datman
        if TESTDATMAN:
            Freesurfersh.write('module load /projects/edickie/privatemodules/datman/edickie\n\n')
        else:
            Freesurfersh.write('module load /archive/data-2.0/code/datman.module\n\n')

        ## to the sinking - unless told not to
        if not NO_SINK:
            Freesurfersh.write('module load AFNI/2014.12.16\n')
            Freesurfersh.write('T1SINK=' + T1sinkdir + ' \n\n')
            Freesurfersh.write('dm-freesurfer-sink.py ${SUBJECTS_DIR} ${T1SINK}\n\n')

        ## add the engima-extract bits
        Freesurfersh.write('ENGIMA_ExtractCortical.sh ${SUBJECTS_DIR} '+ prefix + '\n')
        Freesurfersh.write('ENGIMA_ExtractSubcortical.sh ${SUBJECTS_DIR} '+ prefix + '\n')

    #and...don't forget to close the file
    Freesurfersh.close()

### check the template .sh file that gets submitted to the queue to make sure option haven't changed
def checkrunsh(filename):
    """
    write a temporary (run.sh) file and than checks it againts the run.sh file already there
    This is used to double check that the pipeline is not being called with different options
    """
    tempdir = tempfile.mkdtemp()
    tmprunsh = os.path.join(tempdir,os.path.basename(filename))
    makeFreesurferrunsh(tmprunsh)
    if filecmp.cmp(filename, tmprunsh):
        if DEBUG: print("{} already written - using it".format(filename))
    else:
        # If the two files differ - then we use difflib package to print differences to screen
        print('#############################################################\n')
        print('# Found differences in {} these are marked with (+) '.format(filename))
        print('#############################################################')
        with open(filename) as f1, open(tmprunsh) as f2:
            differ = difflib.Differ()
            print(''.join(differ.compare(f1.readlines(), f2.readlines())))
        sys.exit("\nOld {} doesn't match parameters of this run....Exiting".format(filename))
    shutil.rmtree(tempdir)

####set checklist dataframe structure here
#because even if we do not create it - it will be needed for newsubs_df (line 80)
def loadchecklist(checklistfile,subjectlist):
    """
    Reads the checklistfile (normally called Freesurfer-DTI-checklist.csv)
    if the checklist csv file does not exit, it will be created.

    This also checks if any subjects in the subjectlist are missing from the checklist,
    (checklist.id column)
    If so, they are appended to the bottom of the dataframe.
    """

    cols = ['id', 'T1_nii', 'date_ran','qc_rator', 'qc_rating', 'notes']

    # if the checklist exists - open it, if not - create the dataframe
    if os.path.isfile(checklistfile):
    	checklist = pd.read_csv(checklistfile, sep=',', dtype=str, comment='#')
    else:
    	checklist = pd.DataFrame(columns = cols)

    # new subjects are those of the subject list that are not in checklist.id
    newsubs = list(set(subjectlist) - set(checklist.id))

    # add the new subjects to the bottom of the dataframe
    newsubs_df = pd.DataFrame(columns = cols, index = range(len(checklist),len(checklist)+len(newsubs)))
    newsubs_df.id = newsubs
    checklist = checklist.append(newsubs_df)

    # return the checklist as a pandas dataframe
    return(checklist)

def get_qced_subjectlist(qcchecklist):
    """
    reads the QC checklist and returns a list of all subjects who have passed QC
    """
    qcedlist = []
    if os.path.isfile(rawQCfile):
        with open(rawQCfile) as f:
            for line in f:
                line = line.strip()
                if len(line.split(' ')) > 1:
                    pdf = line.split(' ')[0]
                    subid = pdf.replace('.pdf','')[3:]
                    qcedlist.append(subid)
    else:
        sys.exit("QC file for transfer not found. Try again.")
    ## return the qcedlist (as a list)
    return qcedlist


######## NOW START the 'main' part of the script ##################
## make the putput directory if it doesn't exist
subjectsdir = os.path.abspath(subjectsdir)
log_dir = os.path.join(subjectsdir,'logs')
run_dir = os.path.join(subjectsdir,'bin')
dm.utils.makedirs(log_dir)
dm.utils.makedirs(run_dir)

## find those subjects in input who have not been processed yet
subids_in_nii = dm.utils.get_subjects(inputdir)
subids_in_nii = [ v for v in subids_in_nii if "PHA" not in v ] ## remove the phantoms from the list
## filters for --tag2 if it was specified
if TAG2 != None:
    subids_in_nii = [ v for v in subids_in_nii if TAG2 in v ]
if QCedTranfer:
    # if a QC checklist exists, than read it and only process those participants who passed QC
    qcedlist = get_qced_subjectlist(rawQCfile)
    subids_in_nii = list(set(subids_in_nii) & set(qcedlist)) ##now only add it to the filelist if it has been QCed

# grab the prefix from the subid if not given
if prefix == None: prefix = subids_in_nii[0][0:3]
## writes a standard Freesurfer-DTI running script for this project (if it doesn't exist)
## the script requires a OUTDIR and MAP_BASE variables - as arguments $1 and $2
## also write a standard script to concatenate the results at the end (script is held while subjects run)
runscripts = [runFSsh_name,runPostsh_name]
if POSTFS_ONLY: runscripts = [runPostsh_name]
for runfilename in runscripts:
    runsh = os.path.join(run_dir,runfilename)
    if os.path.isfile(runsh):
        ## create temporary run file and test it against the original
        checkrunsh(runsh)
    else:
        ## if it doesn't exist, write it now
        makeFreesurferrunsh(runsh)

## create an checklist for the T1 maps
checklistfile = os.path.normpath(subjectsdir+'/freesurfer-checklist.csv')
checklist = loadchecklist(checklistfile,subids_in_nii)

## look for new subs using T1_tag and tag2
find_T1images(T1_tag)

## fetch a list of the jobs that are already in the queue
###qstat -xml | tr '\n' ' ' | sed 's#<job_list[^>]*>#\n#g'   | sed 's#<[^>]*>##g' | grep FS_STO | awk -F " " '{print $3}'
qstatcmd="qstat -xml | tr '\\n' ' '" + \
    " | sed 's#<job_list[^>]*>#\\n#g'   | sed 's#<[^>]*>##g' | grep FS_" + \
    prefix + " | awk -F \" \" '{print $3}'"
qstatcall = subprocess.Popen(qstatcmd,shell=True,stdout=subprocess.PIPE)
joblist, err = qstatcall.communicate()
if DEBUG:
    if len(joblist) > 0:
        print("Already submitted jobs for this project are {}".format(joblist))
    else:
        print("No jobs for this project are already sitting in the queue")

## now checkoutputs to see if any of them have been run
#if yes update spreadsheet
#if no submits that subject to the queue
#jobnames = []
## should be in the right run dir so that it submits without the full path
os.chdir(run_dir)
if not POSTFS_ONLY:
    for i in range(0,len(checklist)):
        subid = checklist['id'][i]
        ## make sure that is TAG2 was called - only the tag2s are going to queue
        if (TAG2 != None):
            if (TAG2 not in subid): continue

        ## make sure that a T1 has been selected for this subject
        if pd.isnull(checklist['T1_nii'][i]): continue

        ## make sure that this subject is not sitting in the queue
        jobname = 'FS_' + subid
        if jobname in joblist: continue

        ## check if this subject has already been completed - or started and halted
        FScomplete = os.path.join(subjectsdir,subid,'scripts','recon-all.done')
        FSrunningglob = glob.glob(os.path.join(subjectsdir,subid,'scripts','IsRunning*'))
        FSrunning = FSrunningglob[0] if len(FSrunningglob) > 0 else ''
        # if no output exists than run engima-dti
        if os.path.isfile(FScomplete)== False:
            if os.path.isfile(FSrunning):
                checklist['notes'][i] = "FS halted at {}".format(os.path.basename(FSrunning))
            else:
                ## format contents of T1 column into recon-all command input
                smap = checklist['T1_nii'][i]
                if ';' in smap:
                    base_smaps = smap.split(';')
                else: base_smaps = [smap]
                T1s = []
                for basemap in base_smaps:
                    T1s.append('-i')
                    T1s.append(os.path.join(inputdir,subid,basemap))

                ## submit this subject to the queue
                docmd(['qsub','-N', jobname,  \
                         runFSsh_name, \
                         subid, ' '.join(T1s)])
                ## add today date to the checklist
                checklist['date_ran'][i] = datetime.date.today()




## if any subjects have been submitted,
## submit a final job that will consolidate the resutls after they are finished
if not NO_POST:
    ## This will get all the jobids of using a prefix...
    time.sleep(5) ## sleep 5 seconds to make sure that everything is in the queue
    qstatcall = subprocess.Popen(qstatcmd,shell=True,stdout=subprocess.PIPE)
    joblist, err = qstatcall.communicate()
    post_jobname = 'postFS_'+ prefix
    if ((len(joblist) > 0) & (post_jobname not in joblist)) :
        joblist = joblist.replace('\n',',')
        if joblist[-1] == ',': joblist = joblist[0:-1]
        #if any subjects have been submitted - submit an extract consolidation job to run at the end
        os.chdir(run_dir)
        docmd(['qsub', '-N', post_jobname,  \
            '-hold_jid', joblist, \
            runPostsh_name])

## write the checklist out to a file
checklist.to_csv(checklistfile, sep=',', index = False)
