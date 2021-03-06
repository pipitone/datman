#!/usr/bin/env python

import epitome as epi

def run(input_name):
    output = 'MNI'

    # give us some feedback
    print('\nResampling input EPI data to MNI space using FSL.')

    try:
        # get the reslice dimensions
        print('\nSelect target dimensions (isotropic mm):')
        dims = epi.utilities.selector_float()

    # if we messed any of these up, we return None
    except ValueError as ve:
        return '', None

    # otherwise we print the command and return it
    line = ('. ${DIR_PIPE}/epitome/modules/pre/linreg_epi2mni_fsl ' +
                                              str(input_name) + ' ' +
                                              str(dims))
    return line, output
