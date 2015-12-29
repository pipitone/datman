"""
A collection of utilities for generally munging imaging data. 
"""
import os, sys
import os.path
import re
import dicom as dcm
import zipfile
import tarfile
import io
import glob
import numpy as np
import logging
import subprocess as proc
import scanid
import nibabel as nib

SERIES_TAGS_MAP = {
"T1"         :  "T1",
"T2"         :  "T2",
"DTI"        :  "DTI",
"Back"       :  "NBACK",
"Rest"       :  "REST",
"FLAIR"      :  "FLAIR",
"Imitat"     :  "IMI",
"Observ"     :  "OBS",
"EA.Task"    :  "EMP",
"MRS.sgACC"  :  "MRS-sgACC",
"MRS.DLPFC"  :  "MRS-DLPFC",
"TE6.5"      :  "TE6.5",
"TE8.5"      :  "TE8.5",
"Frac"       :  "ANI",
"Cal"        :  "CAL",
"Loc"        :  "LOC",
} 

def get_subject_from_filename(filename):
    filename = os.path.basename(filename)
    filename = filename.split('_')[0:5]
    filename = '_'.join(filename)

    return filename

def guess_tag(description, tagmap = SERIES_TAGS_MAP): 
    """
    Given a series description return a list of series tags this might be.
    
    By "series tag" we mean a short code like T1, DTI, etc.. that indicates
    more generally what the data is (usually the DICOM header
    SeriesDescription).

    <tagmap> is a dictionary that maps a regex to a series tag, where the regex
    matches the series description dicom header. If not specified this modules
    SERIES_TAGS_MAP is used. 
    """
    matches = list(set(
        [tag for p,tag in tagmap.iteritems() if re.search(p,description)]
        ))
    if len(matches) == 0: return None
    if len(matches) == 1: return matches[0]
    return matches

def mangle_basename(base_path):
    """
    strip off final slash to get the appropriate basename if nessicary.
    """
    if base_path[-1] == '/':
        base = os.path.basename(base_path[0:-1]).lower()
    else:
        base = os.path.basename(base_path).lower()

    return base

def mangle(string): 
    """Mangles a string to conform with the naming scheme.

    Mangling is roughly: convert runs of non-alphanumeric characters to a dash.
    """
    if not string: 
        string = ""
    return re.sub(r"[^a-zA-Z0-9.+]+","-",string)

def get_extension(path): 
    """
    Get the filename extension on this path. 

    This is a slightly more sophisticated version of os.path.splitext in that
    this will correctly return the extension for '.tar.gz' files, for example.
    :D
    """
    if path.endswith('.tar.gz'): 
        return '.tar.gz'
    if path.endswith('.nii.gz'): 
        return '.nii.gz'
    else:
        return os.path.splitext(path)[1]

def splitext(path): 
    """Return the path excluding the extension, and the extension itself.
   
    See os.path.splitext for inspiration. 
    """

    ext = get_extension(path)
    return path[:-len(ext)], ext

def get_archive_headers(path, stop_after_first = False): 
    """
    Get dicom headers from a scan archive.

    Path can be a path to a tarball or zip of dicom folders, or a folder. It is
    assumed that this archive contains the dicoms from a single exam, organized
    into folders for each series.

    The entire archive is scanned and dicom headers from a single file in each
    folder are returned as a dictionary that maps path->headers.
    
    If stop_after_first == True only a single set of dicom headers are
    returned for the entire archive, which is useful if you only care about the
    exam details.
    """
    if os.path.isdir(path): 
        return get_folder_headers(path, stop_after_first)
    elif zipfile.is_zipfile(path):
        return get_zipfile_headers(path, stop_after_first)
    elif os.path.isfile(path) and path.endswith('.tar.gz'):
        return get_tarfile_headers(path, stop_after_first)
    else: 
	raise Exception("{} must be a file (zip/tar) or folder.".format(path))

def get_tarfile_headers(path, stop_after_first = False): 
    """
    Get headers for dicom files within a tarball
    """
    tar = tarfile.open(path)
    members = tar.getmembers()

    manifest = {}
    # for each dir, we want to inspect files inside of it until we find a dicom
    # file that has header information
    for f in filter(lambda x: x.isfile(), members):
        dirname = os.path.dirname(f.name)
        if dirname in manifest: continue
        try:
            manifest[dirname] = dcm.read_file(tar.extractfile(f))
            if stop_after_first: break
        except dcm.filereader.InvalidDicomError, e:
            continue
    return manifest 

def get_zipfile_headers(path, stop_after_first = False): 
    """
    Get headers for a dicom file within a zipfile
    """
    zf = zipfile.ZipFile(path)
    
    manifest = {}
    for f in zf.namelist():
        dirname = os.path.dirname(f)
        if dirname in manifest: continue
        try:
            manifest[dirname] = dcm.read_file(io.BytesIO(zf.read(f)))
            if stop_after_first: break
        except dcm.filereader.InvalidDicomError, e:
            continue
    return manifest 

def get_folder_headers(path, stop_after_first = False): 
    """
    Generate a dictionary of subfolders and dicom headers.
    """

    manifest = {}

    # for each dir, we want to inspect files inside of it until we find a dicom
    # file that has header information 
    subdirs = []
    for filename in os.listdir(path):
        filepath = os.path.join(path,filename)
        try:
            if os.path.isdir(filepath): 
                subdirs.append(filepath)
                continue
            manifest[path] = dcm.read_file(filepath)
            break
        except dcm.filereader.InvalidDicomError, e:
            pass

    if stop_after_first: return manifest

    # recurse
    for subdir in subdirs: 
        manifest.update(get_folder_headers(subdir, stop_after_first))
    return manifest

def get_all_headers_in_folder(path, recurse = False): 
    """
    Get DICOM headers for all files in the given path. 

    Returns a dictionary mapping path->headers for *all* files (headers == None
    for files that are not dicoms).
    """

    manifest = {}
    for dirname, dirnames, filenames in os.walk(path):
        for filename in filenames:
            filepath = os.path.join(dirname,filename)
            headers = None
            try:
                headers = dcm.read_file(filepath)
            except dcm.filereader.InvalidDicomError, e:
                continue
            manifest[filepath] = headers 
        if not recurse: break
    return manifest

def col(arr, colname):
    """
    Return the named column of an ndarray. 

    Column names are given by the first row in the ndarray
    """
    idx = np.where(arr[0,] == colname)[0]
    return arr[1:,idx][:,0]

def subject_type(subject):
    """
    Uses subject naming to determine what kind of files we are looking at. If
    we find a strangely-named subject, we return None.

    TO DEPRICATE.
    """
    try:
        subject = subject.split('_')

        if subject[2] == 'PHA':
            return 'phantom'
        
        elif subject[2] != 'PHA' and subject[2][0] == 'P':
            return 'humanphantom'
        
        elif str.isdigit(subject[2]) == True and len(subject[2]) == 4:
            return 'subject'
        
        else:
            return None

    except:
        return None

def get_subjects(path):
    """
    Finds all of the subject folders in the supplied directory, and returns
    their basenames.
    """
    subjects = filter(os.path.isdir, glob.glob(os.path.join(path, '*')))
    for i, subj in enumerate(subjects):
        subjects[i] = os.path.basename(subj)
    subjects.sort()

    return subjects

def get_phantoms(path):
    """
    Finds all of the phantom folders in the supplied directory, and returns
    their basenames.
    """
    phantoms = []
    subjects = get_subjects(path)
    for subject in subjects:
        subjtype = subject_type(subject)
        if subjtype == 'phantom':
            phantoms.append(subject)

    return phantoms

def get_xnat_catalog(data_path, subject):
    """
    For a given subject, finds and returns all of the xml files as full
    paths. In almost all cases, this will be a single catalog.
    

    THIS IS BROKEN.
    """
    dicoms = os.listdir(os.path.join(data_path, 'dicom'))
    subjects = filter(lambda x: subject in x, dicoms)

    catalogs = []

    for subject in subjects:
        folders = os.listdir(os.path.join(data_path, 'dicom', subject))
        folders.sort()
        files = os.listdir(os.path.join(data_path, 'dicom', subject, 
                                                            folders[0]))
        files = filter(lambda x: '.xml' in x, files)

        catalogs.append(os.path.join(data_path, 'dicom', subject, 
                                                         folders[0],
                                                         files[0]))

    catalogs.sort()

    return catalogs

def define_folder(path):
    """
    Sets a variable to be the path to a folder. Also, if the folder does not 
    exist, this makes it so, unless we lack the permissions to do so, which
    leads to a graceful exit.
    """
    if os.path.isdir(path) == False:
        try:
            os.mkdir(path)
        except:
            if has_permissions(path) == False:
                sys.exit()

    if has_permissions(path) == False:
        sys.exit()

    return path

def has_permissions(path):
    """
    Checks for write access to submitted path.
    """
    if os.access(path, 7) == True:
        flag = True
    else:
        print('\nYou do not have write access to path ' + str(path))
        flag = False

    return flag

def make_epitome_folders(path, n_runs):
    """
    Makes an epitome-compatible folder structure with functional data FUNC of n
    runs, and a single T1.

    This works assuming we've run everything through freesurfer.

    If we need multisession, it might make sense to run this multiple times
    (once per session).
    """
    run('mkdir -p ' + path + '/TEMP/SUBJ/T1/SESS01/RUN01')
    for r in np.arange(n_runs)+1:
        num = "{:0>2}".format(str(r))
        run('mkdir -p ' + path + '/TEMP/SUBJ/FUNC/SESS01/RUN' + num)

def run_dummy_q(list_of_names):
    """
    This holds the script until all of the queued items are done.
    """
    print('Holding for remaining processes.')
    opts = 'h_vmem=3G,mem_free=3G,virtual_free=3G'
    holds = ",".join(list_of_names)
    cmd = 'qsub -sync y -hold_jid {} -l {} -b y echo'.format(holds, opts)
    run(cmd)
    print('... Done.')

def run(cmd, dryrun=False, echo=False):
    """
    Runs a command in the default shell (so beware!)

    Returns the return code, stdout and stderr.
    """
    if dryrun: 
        return 0, "", ""

    stdout = echo and None or proc.PIPE
    stderr = echo and None or proc.PIPE

    p = proc.Popen(cmd, shell=True, stdout=stdout, stderr=stderr)
    out, err = p.communicate() 
    return p.returncode, out, err

def get_files_with_tag(parentdir, tag, fuzzy = False):
    """
    Returns a list of files that have the specified tag. 

    Filenames must conform to the datman naming convention (see
    scanid.parse_filename) in order to be considered. 

    If fuzzy == True, then filenames are matched if the given tag is found
    within the filename's tag. 
    """

    files = []
    for f in os.listdir(parentdir): 
        try:
            _, filetag, _, _ = scanid.parse_filename(f)
            if tag == filetag or (fuzzy and tag in filetag): 
                files.append(os.path.join(parentdir,f))
        except scanid.ParseException:
            continue
            
    return files

def makedirs(path): 
    """
    Make the directory (including parent directories) if they don't exist
    """
    if not os.path.exists(path):
        os.makedirs(path)

def loadnii(filename):
    """
    Usage:
        nifti, affine, header, dims = loadnii(filename)

    Loads a Nifti file (3 or 4 dimensions).
    
    Returns: 
        a 2D matrix of voxels x timepoints, 
        the input file affine transform, 
        the input file header, 
        and input file dimensions.
    """

    # load everything in
    nifti = nib.load(filename)
    affine = nifti.get_affine()
    header = nifti.get_header()
    dims = nifti.shape

    # if smaller than 3D
    if len(dims) < 3:
        raise Exception('Your data has less than 3 dimensions!')

    # if smaller than 4D
    if len(dims) > 4:
        raise Exception('Your data is at least a penteract (> 4 dimensions!)')
    
    # load in nifti and reshape to 2D
    nifti = nifti.get_data()
    if len(dims) == 3:
        dims = tuple(list(dims) + [1])
    nifti = nifti.reshape(dims[0]*dims[1]*dims[2], dims[3])

    return nifti, affine, header, dims

def check_returncode(returncode):
    if returncode != 0:
        raise ValueError

# vim: ts=4 sw=4 sts=4:
