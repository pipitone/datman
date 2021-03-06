#!/usr/bin/env python

import epitome as epi

def run(input_name):
    output = 'detrend'

    print('\nAdding detrend module.')

    try:
        print('\nSet detrend order:')
        polort = epi.utilities.selector_int()

    # if we messed any of these up, we return None
    except ValueError as ve:
        return '', None

    # otherwise we print the command and return it
    line = ('. ${{DIR_PIPE}}/epitome/modules/pre/detrend {input_name} {polort}').format(
                              input_name=str(input_name),
                              polort=str(polort))

    return line, output
