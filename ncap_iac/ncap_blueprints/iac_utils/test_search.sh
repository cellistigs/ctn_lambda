#!/bin/bash
## Note this file is for internal testing of lambda functions, and references main_func_env_vars, a CtN AWS account specific resource. 
### Script that automates the testing of submission lambda functions 
set -e
scriptdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
ncaprootdir="$(dirname "$(dirname "$scriptdir")")"

source "$scriptdir"/paths.sh
## Get the path to this particular file. 
## NOTE: Add the anaconda path if running as admin.  
source activate neurocaas

## Input management: 
## Get the path to the directory where user data is stored: 
[ -d "$1" ] || { echo "ERROR: Must give path to analysis stack directory"; exit; }

PIPEDIR=$(get_abs_filename "$1")

## This can give us the stack name: 
cd $PIPEDIR

## Test main lambda function
sam local invoke SearchLambda --event test_resources/s3_putevent_end.json -n test_resources/main_func_env_vars.json 
