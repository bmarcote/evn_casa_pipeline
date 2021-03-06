#!casa -c
# Should be something like !/usr/bin/env casa   Does it work?

"""EVN CASA Pipeline.


@author: Benito Marcote
@contact: marcote@jive.eu
@license: GPL??
@date: 2018/04/11
@version: 0.0.1

"""
_prog = 'EVN_CASA.py'
_usage = 'usage: %prog [-h] <input_file>'
_description = """EVN Pipeline"""
_version = '1.0.0'
_date = '2018/04/11'
_default_input_file = '/home/marcote/Programing/evn_casa_pipeline/setup_files/default_inputs.inp'


import os
import sys
import glob
import shutil
import ConfigParser
import logging
import datetime
from collections import defaultdict, namedtuple
import numpy as np
from casa import *
from recipes import tec_maps

# Fix for now
sys.path.append('/home/marcote/Programing/evn_casa_pipeline/')
sys.path.append('/home/marcote/Programing/evn_casa_pipeline/analysis_scripts/')
import useful_functions as uf
import analysisUtils as au


input_file = sys.argv[-1]


######### Loading the input file

# Checks that both, the default one and the input one exists
if not os.path.isfile(_default_input_file):
    # logger.exception('Default input file not found (expected at {})'.format(_default_input_file))
    raise IOError('File {} not found.'.format(_default_input_file))

if not os.path.isfile(input_file):
    # logger.exception('Input file {} not found.'.format(input_file))
    raise IOError('File {} not found.'.format(input_file))

config = ConfigParser.ConfigParser()
# Read the file with all the default parameters to use in the pipeline
config.read(_default_input_file)
# Upload the parameters with the inputs from the user (the provided file)
config.read(input_file)

parameters = defaultdict(dict)

# Interpret all parameters to their correct type (integers, booleans, str, lists)
# DEFAULT section appears independently
for a_param in config.defaults():
    parameters['DEFAULT'][a_param] = uf.evaluate(config.defaults()[a_param])

for a_section in config.sections():
    for a_param in config.options(a_section):
        # Only those ones that are not in DEFAULTS
        if a_param not in parameters['DEFAULT']:
            parameters[a_section][a_param] = uf.evaluate(config.get(a_section, a_param))


######### Let's create the logger
logger = logging.getLogger(__name__)
logger_stdout = logging.StreamHandler(stream=sys.stdout)
logger_errlog = logging.FileHandler(filename=parameters['DEFAULT']['logger'])

# Formatters TODO
# logger_formatter = logging.Formatter('%(levelname)s: %(name)s  -  %(message)s')
# logger_stdout.setFormatter(logger_formatter)
# logger_errlog.setFormatter(logger_formatter)

logger.addHandler(logger_errlog)
logger.addHandler(logger_stdout)

logger.setLevel('DEBUG')
logger_errlog.setLevel('DEBUG')
logger_stdout.setLevel('DEBUG')


###################### Starting the pipeline

times = [] # Will keep an ordered sample of times
times.append(datetime.datetime.now())

logger.info('EVN CASA Pipeline starting at {}'.format(times[-1]))


# Pre-processing steps are required. See CASA tutorial (gc.py, antabs..)


# tmask can be just an integer or also a couple of integers (first, and last step to execute)
if type(parameters['DEFAULT']['tmask']) == int:
    parameters['DEFAULT']['tmask'] = (parameters['DEFAULT']['tmask'], 999)

assert parameters['DEFAULT']['tmask'][0] <= parameters['DEFAULT']['tmask'][1]

logger.info('Pipeline to execute steps (tmask) from {} to {}'.format(parameters['DEFAULT']['tmask'][0],
                                                                      parameters['DEFAULT']['tmask'][1]))


# Check if this is a phase-referencing experiment
if parameters['DEFAULT']['phaseref'] is not None:
    if len(parameters['DEFAULT']['phaseref']) != len(parameters['DEFAULT']['target']):
        logger.exception('The parameters phaseref and target must contain the same number of source.')
        raise NameError('phaseref and target must contain the same number of sources')

# Check that all directories exist  os.path.isdir
for a_dir_name in ('fitsdir', 'indir', 'outdir', 'pipedir', 'setupdir'):
    # Removes the trailing / if it is present in all directories path
    if parameters['DEFAULT'][a_dir_name].strip()[-1] == '/':
        parameters['DEFAULT'][a_dir_name] = parameters['DEFAULT'][a_dir_name].strip()[:-1]

    if not os.path.isdir(parameters['DEFAULT'][a_dir_name]):
        if parameters['DEFAULT']['create_new_directories']:
            os.makedirs(parameters['DEFAULT'][a_dir_name])

        else:
            raise FileNotFoundError('No such file or directory: {}'.format(a_dir))

# Make sure all inputs related to sources are lists (even if only one source specified)
if type(parameters['DEFAULT']['bpass']) is not list:
    parameters['DEFAULT']['bpass'] = [ parameters['DEFAULT']['bpass'] ]

if parameters['DEFAULT']['phaseref'] is not None:
    if type(parameters['DEFAULT']['phaseref']) is not list:
        parameters['DEFAULT']['phaseref'] = [ parameters['DEFAULT']['phaseref'] ]

    if type(parameters['DEFAULT']['target']) is not list:
        parameters['DEFAULT']['target'] = [ parameters['DEFAULT']['target'] ]

    assert len(parameters['DEFAULT']['phaseref']) == len(parameters['DEFAULT']['target'])

# Dict with all the necessary files that are going to be used
# By default:
#  - msdata (original MS file with the raw data)
#  - {source}:
#       - split
#       - clean
#       - dirty
#       -


msfiles = uf.build_required_msfile_names(parameters['DEFAULT'])
fitsfiles = uf.build_required_fitsfile_names(parameters['DEFAULT'])
calfiles = uf.build_required_calfile_names(parameters['DEFAULT'])
plotfiles = uf.build_required_plotfile_names(parameters['DEFAULT'])
calfilesapplied = []
spwmaplist = []

outpreffix = parameters['DEFAULT']['outdir'] + '/' + parameters['DEFAULT']['experiment']

# Two files expected in the indir directory: experiment.uvflag and experiment.antab
# both in CASA-like format.
uvflgfile = parameters['DEFAULT']['indir']+'/'+parameters['DEFAULT']['experiment']+'.uvflag'
antabfile = parameters['DEFAULT']['indir']+'/'+parameters['DEFAULT']['experiment']+'.antab'
evngcfile = parameters['DEFAULT']['indir']+'/EVN.gc'


################ Inspecting the data

# Information related to the raw MS data, as 'channels', 'subbands' (number of), 'sources'
msinfo = uf.get_info_from_ms(msfiles['msdata'])

# Updating all the sources to consider (either specified in sources, or accounting for bpass/phaseref/target
# Just wait to see following lines, I will only leave the good ones.
if parameters['DEFAULT']['sources'] == None:
    msinfo['calibrators'] = msinfo['sources']
else:
    msinfo['sources'] = parameters['DEFAULT']['sources']
    msinfo['calibrators'] = parameters['DEFAULT']['sources']

# Remove the targets from the calibrators (calibrators defined as sources to use in fringe)
if parameters['DEFAULT']['phaseref'] is not None:
    for a_target in parameters['DEFAULT']['target']:
        msinfo['calibrators'].remove(a_target)


if parameters['DEFAULT']['tmask'][0] <= 1 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Inspection of the data')
    times.append(datetime.datetime.now())
    logger.info('Starting at {}'.format(times[-1]))
    logger.info('Running listobs...')
    listobs(vis=msfiles['msdata'], listfile=outpreffix+'.SCAN', overwrite=True)
    if parameters['DEFAULT']['doplot']:
        logger.info('Running plotants...')
        plotants(vis=msfiles['msdata'], figfile=outpreffix+'.plotants.pdf')
        for a_source in paramters['DEFAULT']['sources']:
            logger.info('Running plotuv...')
            plotuv(vis=msfiles['msdata'], field=a_source, figfile=outpreffix+'_'+ \
                   a_source+'.uvcov.pdf')

    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ A-priori data flagging
if parameters['DEFAULT']['tmask'][0] <= 2 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'A-priori data flagging')
    if os.path.isfile(uvflgfile):
        flagdata(vis=msfiles['msdata'], mode='list', inpfile=uvflgfile, reason='Default flags',
                 tbuff=0.0, action='apply', display='', flagbackup=True, savepars=False)

    else:
        logger.warning('WARNING: No uvflag file found at {}. No default flags applied.'.format(uvflgfile))

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))



################ Plotting uncalibrated data
if parameters['DEFAULT']['tmask'][0] <= 3 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Plotting uncalibrated data')
    if parameters['DEFAULT']['doplot']:
        # plotms(msfiles['msdata'], gridrows=3, gridcols=3, xaxis='spw', yaxis='amp', ydatacolumn='data',
        #        field=','.join(parameters['DEFAULT']['bpass']), correlation='rr,ll', avgscan=True,
        #        iteraxis='scan,antenna,corr', showlegend=True, plotfile=plotfiles['uncal']['autocorr'],
        #        exprange='all', dpi=300, overwrite=True, showgui=False, clearplots=True)
        logger.warning('Plotting uncalibrated data not implemented yet.')

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Generate a-priori calibration tables (Tsys and gain curve).
if parameters['DEFAULT']['tmask'][0] <= 4 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Generating a-priori calibration tables')
    # Remove the calibration previous if they already exist
    if os.path.exists(calfiles['tsys']):
        shutil.rmtree(calfiles['tsys'])

    if os.path.exists(calfiles['gc']):
        shutil.rmtree(calfiles['gc'])

    gencal(vis=msfiles['msdata'], caltable=calfiles['tsys'], caltype='tsys', uniform=False)
    gencal(vis=msfiles['msdata'], caltable=calfiles['gc'], caltype='gc', infile=evngcfile)
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))
    if parameters['DEFAULT']['doplot']:
        plotcal(caltable=calfiles['tsys'], xaxis='time', yaxis='tsys', subplot=911, overplot=False,
                iteration='antenna,spw', showgui=False, figfile=plotfiles['tsys'])
        plotcal(caltable=calfiles['gc'], #xaxis='time', yaxis='tsys', subplot=911, overplot=False,
                #iteration='antenna,spw', showgui=False,
                figfile=plotfiles['gc'])



calfilesapplied.append(calfiles['tsys'])
calfilesapplied.append(calfiles['gc'])
spwmaplist.append([])
spwmaplist.append([])

################ Instrumental delay calibration and Ionospheric corrections

if parameters['DEFAULT']['tmask'][0] <= 5 <= parameters['DEFAULT']['tmask'][1]:
    if parameters['DEFAULT']['do_ionospheric_correction']:
        if os.path.exists(calfiles['tec']):
            shutil.rmtree(calfiles['tec'])

        uf.print_log_header(logger, 'Ionospheric corrections (tecor)')
        tec_image, tec_rms_image, tec_graph = tec_maps.create(msfiles['msdata'], doplot=False)
        gencal(vis=msfiles['msdata'], caltype='tecim', caltable=calfiles['tec'], infile=tec_image)
        calfilesapplied.append(calfiles['tec'])
        spwmaplist.append([])
        times.append(datetime.datetime.now())
        logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))

    if parameters['DEFAULT']['do_fringe_instrumental']:
        uf.print_log_header(logger, 'Instrumental delay calibration (fringe)')
        if os.path.exists(calfiles['fringe_instr']):
            shutil.rmtree(calfiles['fringe_instr'])

        fringefit(vis=msfiles['msdata'], caltable=calfiles['fringe_instr'], field='',
                  gaintable=[calfiles[i] for i in ('tsys', 'gc')], spwmap=spwmaplist,
                  **parameters['fringe_instrumental'])

        calfilesapplied.append(calfiles['fringe_instr'])
        spwmaplist.append([])
        times.append(datetime.datetime.now())
        logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))
        if parameters['DEFAULT']['doplot']:
            logger.info('Creating plots from the instrumental fringe calibration.')
            plotcal(calfiles['fringe_instr'], xaxis='freq', yaxis='phase', iteration='antenna', subplot=911,
                    figfile=plotfiles['fringe_instr']['phase'])
            plotcal(calfiles['fringe_instr'], xaxis='freq', yaxis='delay', iteration='antenna', subplot=911,
                    figfile=plotfiles['fringe_instr']['delay'])
            times.append(datetime.datetime.now())
            logger.info('Finishing plots at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))



################ Calibrate and self-calibrate only in a fringe-finder to deduce the amp. cal problems?

if parameters['DEFAULT']['tmask'][0] <= 5 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Calibrated and self-calibrate the fringe-finder')
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))



################ Global fringe fitting

if parameters['DEFAULT']['tmask'][0] <= 5 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Global fringe')
    if os.path.exists(calfiles['fringe']):
        shutil.rmtree(calfiles['fringe'])

    # Sanity check
    if (not parameters['DEFAULT']['do_fringe_instrumental']) and (parameters['fringe']['combine'] == 'spw'):
        logger.warning('Global fringe is combining subbands but an instrumental delay fringe was not performed.')

    fringefit(vis=msfiles['msdata'], caltable=calfiles['fringe'], field=','.join(msinfo['calibrators']),
          gaintable=calfilesapplied, spwmap=spwmaplist, **parameters['fringe'])
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))
    if parameters['DEFAULT']['doplot']:
        logger.info('Creating plots from the fringe calibration.')
        plotcal(calfiles['fringe'], xaxis='time', yaxis='phase', iteration='antenna', subplot=911,
                figfile=plotfiles['fringe']['phase'])
        plotcal(calfiles['fringe'], xaxis='time', yaxis='delay', iteration='antenna', subplot=911,
                figfile=plotfiles['fringe']['delay'])
        plotcal(calfiles['fringe'], xaxis='time', yaxis='rate', iteration='antenna', subplot=911,
                figfile=plotfiles['fringe']['rate'])
        times.append(datetime.datetime.now())
        logger.info('Finishing plots at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))

calfilesapplied.append(calfiles['fringe'])
spwmaplist.append([0]*msinfo['subbands'])



################ Bandpass calibration

if parameters['DEFAULT']['tmask'][0] <= 6 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Bandpass calibration')
    if os.path.exists(calfiles['bpass']):
        shutil.rmtree(calfiles['bpass'])

    # Sanity check. remove duplicate entries
    if 'field' in parameters['bandpass']:
        parameters['bandpass'].pop('field')

    bandpass(vis=msfiles['msdata'], caltable=calfiles['bpass'], field=','.join(parameters['DEFAULT']['bpass']),
            gaintable=calfilesapplied, spwmap=spwmaplist, **parameters['bandpass'])
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))
    if parameters['DEFAULT']['doplot']:
        plotcal(calfiles['bpass'], subplot=441, iteration='antenna,spw', showgui=False, figfile=plotfiles['bpass'])


calfilesapplied.append(calfiles['bpass'])
spwmaplist.append([])


################ Apply calibration

if parameters['DEFAULT']['tmask'][0] <= 7 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Applying calibration')
    # TODO: I assume that I should apply individually for each source to avoid problems...
    applycal(vis=msfiles['msdata'], field=','.join(msinfo['sources']), gaintable=calfilesapplied,
            spwmap=spwmaplist, **parameters['applycal'])
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Do plots of calibrated data (still in tmask 7)

if parameters['DEFAULT']['tmask'][0] <= 7 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Plotting calibrated data')
    if parameters['DEFAULT']['doplot']:
        pass

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Split files

if parameters['DEFAULT']['tmask'][0] <= 8 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Removing existing split files')
    if os.path.exists(msfiles['split']):
        shutil.rmtree(msfiles['split'])

    uf.print_log_header(logger, 'Creating split files')
    split(vis=msfiles['msdata'], outputvis=msfiles['split'], field=','.join(msinfo['sources']),
          datacolumn='corrected')
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Store split files

if parameters['DEFAULT']['tmask'][0] <= 9 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Storing split files as uvfits')
    for a_source in msinfo['sources']:
        exportuvfits(vis=msfiles['msdata'], fitsfile=fitsfiles[a_source]['uvdata'],
                    field=a_source, multisource=False, overwrite=True)

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Create dirty maps and lean maps

if parameters['DEFAULT']['tmask'][0] <= 10 <= parameters['DEFAULT']['tmask'][1]:
    temp_niter = parameters['clean'].pop('niter')
    # Getting the optimal cellsize depending on the robust
    if parameters['clean']['weighting'] == 'natural':
        cellsize = str(msinfo['resolution']/10.)+'mas'
    elif parameters['clean']['weighting'] == 'uniform':
        cellsize = str(msinfo['resolution']/40.)+'mas'
    else:
        cellsize = '{:4f}mas'.format(msinfo['resolution']/(-30/4.*parameters['clean']['robust']+25))

    if parameters['DEFAULT']['target'] is not None:
        for a_target in parameters['DEFAULT']['target']:
            uf.print_log_header(logger, 'Removing existing dirty image files')
            prev_images = glob.glob(msfiles[a_target]['dirty']+'*')
            for prev_image in prev_images:
                shutil.rmtree(prev_image)

            uf.print_log_header(logger, 'Creating dirty images for {}.'.format(a_target))
            tclean(vis=msfiles['split'], imagename=msfiles[a_target]['dirty'], field=a_target, spw='', niter=0,
                cell=cellsize, **parameters['clean'])

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))

    parameters['clean']['niter'] = temp_niter
    for a_cal in msinfo['calibrators']:
        uf.print_log_header(logger, 'Removing existing clean image files')
        prev_images = glob.glob(msfiles[a_cal]['clean']+'*')
        for prev_image in prev_images:
            shutil.rmtree(prev_image)

        uf.print_log_header(logger, 'Cleaning maps for {}'.format(a_cal))
        tclean(vis=msfiles['split'], imagename=msfiles[a_cal]['clean'], field=a_cal, spw='',
            cell=cellsize, savemodel='modelcolumn', **parameters['clean'])

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Do plots of images??

if parameters['DEFAULT']['tmask'][0] <= 11 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Plotting images')
    if parameters['DEFAULT']['doplot']:
        pass

    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Calculate antenna sensitivities from the fringe finder

if parameters['DEFAULT']['tmask'][0] <= 12 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Calculating antenna sensitivities from the fringe finder')
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


################ Save all final products and plot final map

if parameters['DEFAULT']['tmask'][0] <= 13 <= parameters['DEFAULT']['tmask'][1]:
    uf.print_log_header(logger, 'Saving final products and plotting final maps')
    times.append(datetime.datetime.now())
    logger.info('Finishing at {}. It took {} s.'.format(times[-1], (times[-1]-times[-2]).total_seconds()))


logger.info('The pipeline finished happily after {:.2f} min.'.format((times[-1]-times[0]).total_seconds()/60.))

