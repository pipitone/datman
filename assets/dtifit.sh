#!/bin/bash
function usage {
echo "
Runs eddy_correct, bet and dtifit on a dwi image

Usage: 
   dtifit.sh <dwifile.nii.gz> <outputdir> <ref_vol> <fa_thresh>

"
}
set -e

dwifile="$1"
outputdir="$2"
ref_vol="$3"
fa_thresh="$4"

if [ $# -ne 4 ]; then 
  usage;
  exit 1;
fi

# input files
stem=$(basename $dwifile .nii.gz)
dwidir=$(dirname $dwifile)
bvec=${dwidir}/${stem}.bvec
bval=${dwidir}/${stem}.bval

# output files
eddy=${outputdir}/${stem}_eddy_correct
bet=${eddy}_bet
mask=${bet}_mask
dtifit=${eddy}_dtifit

eddy_correct ${dwifile} ${eddy} ${ref_vol}
bet ${eddy} ${bet} -m -f ${fa_thresh}
dtifit -k ${eddy} -m ${mask} -r ${bvec} -b ${bval} --save_tensor -o ${dtifit}
cp ${bvec} ${eddy}.bvec
cp ${bval} ${eddy}.bval
