#!/usr/bin/env python
"""
This builds a Github Pages site using the phantom (and possibly other) QC
plots generated by datman, commits those changes, and finally pushes them
up to github. This way, the online dashboards can be updated automatically.

Usage:
    web-build.py [options] <project>

Arguments: 
    <project>           Full path to the project directory containing data/.

Options:
    -v,--verbose             Verbose logging
    --debug                  Debug logging

DETAILS

    This finds outputs of qc-phantom.py (and potentially eventually qc.py),
    and syncs them to the website project for rendering on the web.

    This assumes you've set up the website/ folder using the template. 

    This message is printed with the -h, --help flags.
"""

import sys, os
from copy import copy
from docopt import docopt
import datman as dm
import sqlite3

VERBOSE = False
DRYRUN  = False
DEBUG   = False

def get_latest_files(base_path):
    """
    This gets the output .csvs for the adni, fmri, and dti qc plots, and 
    returns the paths to each. If a type of these outputs does not exist 
    for a given study, we return None for that type.
    """
    try:
        adni = os.listdir('{}/qc/phantom/adni'.format(base_path))
        adni = filter(lambda x: '_adni_' in x and 'csv' in x, adni)
        adni.sort()
        adni = adni[-9:]
    except:
        adni = None

    try:
        fmri = os.listdir('{}/qc/phantom/fmri'.format(base_path))
        fmri = filter(lambda x: '_fmri_' in x and 'csv' in x, fmri)
        fmri.sort()
        fmri = fmri[-7:]
    except:
        fmri = None

    try:
        dti = os.listdir('{}/qc/phantom/dti'.format(base_path))
        dti = filter(lambda x: '_dti_' in x and 'csv' in x, dti)
        dti.sort()
        dti = dti[-1:]
    except:
        dti = None

    return adni, fmri, dti

def get_imagetype_from_filename(filename):
    """
    Determines the type of plot from the filename.
    """
    if 'adni' in filename.lower():
        imagetype = 'adni'
    elif 'fmri' in filename.lower():
        imagetype = 'fmri'
    elif 'dti' in filename.lower():
        imagetype = 'dti'
    else:
        print('ERROR: Unknown input file ' + f)
        imagetype = None

    return imagetype

def convert_to_web(base_path, files):
    """
    Converts .pdfs to .pngs in the website folder. Also changes the associated
    filenames to contain the new file extensions.
    """
    for i, f in enumerate(files):
        imagetype = get_imagetype_from_filename(f)
        cmd = ('rsync '
               '{base_path}/qc/phantom/{imagetype}/{f} '
               '{base_path}/website/assets/{output}'.format(
                    base_path=base_path, imagetype=imagetype, 
                    f=f, output=f[9:]))
        os.system(cmd)

def parse_db_cols(cur, table):
    """
    Get the column names from the database.
    """
    cur.execute('PRAGMA table_info({})'.format(table))
    d = cur.fetchall()

    cols = []
    for col in d:
        cols.append(str(col[1]))

    return cols

def get_subjects(cur, table):
    """
    Get all of the subjects from the specified table in the database.
    """
    cur.execute('SELECT subj FROM {}'.format(table))
    d = cur.fetchall()

    subj = []
    for sub in d:
        subj.append(str(sub[0]))
    subj.sort()

    return subj

def get_sites(subj):
    """
    From a list of subjects, return the unique sites.
    """
    sites = []
    for sub in subj:
        sites.append(sub.split('_')[1])
    sites = list(set(sites))
    sites.sort()

    return sites

def get_data(cur, table, col):
    """
    Get all of the data from a specified table in the database.
    """
    cur.execute('SELECT {} FROM {}'.format(col, table))
    d = cur.fetchall()

    data = []
    for dat in d:
        data.append(dat[0])

    return data


# def read_subj_qc_database(base_path):
#     """
#     """
#     db = sqlite3.connect('{}/qc/subject-qc.db'.format(base_path))
#     cur = db.cursor()

#     fmri_cols = parse_db_cols(cur, 'fmri')
#     dti_cols = parse_db_cols(cur, 'dti')

#     fmri_subj = get_subjects(cur, 'fmri')
#     dti_subj = get_subjects(cur, 'dti')
#     subj = list(set().union(fmri_subj + dti_subj))
#     subj.sort()

#     sites = get_sites(subj)

#     output = []
#     # construct header
#     o = []
#     o.append('x')
#     #o.append('date')
#     for s in sites:
#         o.append(str(s))
#         o.append(str(s)+'_names')
#     output.append(o)

#     subjdata = []
#     for i, site in enumerate(sites):
#         sitesubj = filter(lambda x: site in x, subj)
#         subjdata[i] = sitesubj

#         for j, subj in enumerate(sitesubj):



#     for plotnum, plot in enumerate(array):

#         # construct string dict
#         datedict = {}
#         for row in np.arange(len(l)):
#             weeknum = l[row]
#             for s in np.arange(len(sites)):
#                 for i, week in enumerate(timearray[s]):
#                     if weeknum == week:
#                         datedict[week] = discarray[s][i]

#         # now add the data
#         for row in np.arange(len(l)):
#             o = []
#             o.append(row)

#             # append the string discription for the first site that matches
#             weeknum = l[row]
#             # o.append(datedict[weeknum])

#             for s in np.arange(len(sites)):
#                 tmp = list(timearray[s])
#                 try:
#                     idx = tmp.index(weeknum)
#                     o.append(plot[s][idx])
#                 except:
#                     o.append('')
#             output.append(o)

def main():

    arguments = docopt(__doc__)
    project   = arguments['<project>']
    VERBOSE   = arguments['--verbose']
    DEBUG     = arguments['--debug']

    # gets a list of all the unposted pdfs
    adni, fmri, dti = get_latest_files(project)

    # syncs latest csv files (from qc-phantom.py) to website
    if adni:
        print('converting ADNI')
        convert_to_web(project, adni)
        
    if fmri:
        print('updating fMRI')
        convert_to_web(project, fmri)
        
    if dti:
        print('updating DTI')
        convert_to_web(project, dti)

    # # update subject data directly from subject-qc.db
    # if subj:
    #     print('updating SUBJ')
    #     subj = read_subj_qc_database(project)

if __name__ == '__main__':
    main()
