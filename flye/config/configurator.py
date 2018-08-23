#(c) 2013-2016 by Authors
#This file is a part of ABruijn program.
#Released under the BSD license (see LICENSE file)

"""
Sets up some parameters for the run based on input
"""

import logging

import flye.utils.fasta_parser as fp
import flye.config.py_cfg as cfg


logger = logging.getLogger()


def setup_params(args):
    logger.info("Configuring run")
    parameters = {}

    total_length = 0
    read_lengths = []
    for read_file in args.reads:
        for seq, seq_len in fp.read_sequence_lengths(read_file).iteritems():
            total_length += seq_len
            read_lengths.append(seq_len)

    _, reads_n50 = _calc_nx(read_lengths, total_length, 0.50)
    _, reads_n90 = _calc_nx(read_lengths, total_length, 0.90)

    #Selecting minimum overlap
    logger.debug("Total sequence length: {0}".format(total_length))

    coverage = total_length / args.genome_size
    logger.info("Input genome size: {0}".format(args.genome_size))
    logger.info("Estimated coverage: {0}".format(coverage))
    if coverage < 5 or coverage > 1000:
        logger.warning("Expected read coverage is " + str(coverage) +
                       ", the assembly is not " +
                       "guaranteed to be optimal in this setting." +
                       " Are you sure that the genome size " +
                       "was entered correctly?")

    logger.info("Reads N50/N90: {0} / {1}".format(reads_n50, reads_n90))
    if args.min_overlap is None:
        GRADE = 1000
	int_min_ovlp = int(float(reads_n90) / GRADE) * GRADE

        parameters["min_overlap"] = \
            max(cfg.vals["min_overlap_range"][args.read_type][0],
                min(cfg.vals["min_overlap_range"][args.read_type][1], int_min_ovlp))
        logger.info("Minimum overlap set to {0}".format(parameters["min_overlap"]))
    else:
        parameters["min_overlap"] = args.min_overlap

    #Selecting k-mer size
    if args.genome_size < cfg.vals["big_genome_kmer"]:
        parameters["kmer_size"] = cfg.vals["kmer_size"][args.read_type][0]
    else:
        parameters["kmer_size"] = cfg.vals["kmer_size"][args.read_type][1]
    logger.info("Selected k-mer size: {0}".format(parameters["kmer_size"]))

    #Selecting read subsample...
    pass

    return parameters


def _calc_nx(scaffolds_lengths, assembly_len, rate):
    n50 = 0
    sum_len = 0
    l50 = 0
    for l in sorted(scaffolds_lengths, reverse=True):
        sum_len += l
        l50 += 1
        if sum_len > rate * assembly_len:
            n50 = l
            break
    return l50, n50
