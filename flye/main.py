#(c) 2016 by Authors
#This file is a part of ABruijn program.
#Released under the BSD license (see LICENSE file)

"""
Main logic of the package
"""

from __future__ import print_function
import sys
import os
import logging
import argparse
import json
import shutil
import subprocess

import flye.polishing.alignment as aln
import flye.polishing.polish as pol
import flye.polishing.consensus as cons
import flye.assembly.assemble as asm
import flye.assembly.repeat_graph as repeat
import flye.assembly.scaffolder as scf
from flye.__version__ import __version__
import flye.config.py_cfg as cfg
from flye.config.configurator import setup_params
from flye.utils.bytes2human import human2bytes
import flye.utils.fasta_parser as fp
from flye.short_plasmids.main import assemble_short_plasmids


logger = logging.getLogger()

class ResumeException(Exception):
    pass

class Job(object):
    """
    Describes an abstract list of jobs with persistent
    status that can be resumed
    """
    run_params = {"stage_name" : ""}

    def __init__(self):
        self.name = None
        self.args = None
        self.work_dir = None
        self.out_files = {}
        self.log_file = None

    def run(self):
        pass

    def save(self, save_file):
        Job.run_params["stage_name"] = self.name

        with open(save_file, "w") as fp:
            json.dump(Job.run_params, fp)

    def load(self, save_file):
        with open(save_file, "r") as fp:
            data = json.load(fp)
            Job.run_params = data

    def completed(self, save_file):
        with open(save_file, "r") as fp:
            data = json.load(fp)

            for file in self.out_files.values():
                if not os.path.exists(file):
                    return False

            return True


class JobConfigure(Job):
    def __init__(self, args, work_dir):
        super(JobConfigure, self).__init__()
        self.args = args
        self.work_dir = work_dir
        self.name = "configure"

    def run(self):
        params = setup_params(self.args)
        Job.run_params = params


class JobAssembly(Job):
    def __init__(self, args, work_dir, log_file):
        super(JobAssembly, self).__init__()
        #self.out_assembly = out_assembly
        self.args = args
        self.work_dir = work_dir
        self.log_file = log_file

        self.name = "assembly"
        self.assembly_dir = os.path.join(self.work_dir, "0-assembly")
        self.assembly_filename = os.path.join(self.assembly_dir,
                                              "draft_assembly.fasta")
        self.out_files["assembly"] = self.assembly_filename

    def run(self):
        if not os.path.isdir(self.assembly_dir):
            os.mkdir(self.assembly_dir)
        asm.assemble(self.args, Job.run_params, self.assembly_filename,
                     self.log_file, self.args.asm_config, )
        if os.path.getsize(self.assembly_filename) == 0:
            raise asm.AssembleException("No contigs were assembled - "
                                        "please check if the read type and genome "
                                        "size parameters are correct")


class JobShortPlasmidsAssembly(Job):
    def __init__(self, args, work_dir, contigs_file):
        super(JobShortPlasmidsAssembly, self).__init__()

        self.args = args
        self.work_dir = work_dir
        self.plasmids_dir = os.path.join(work_dir, "2b-plasmids")
        self.contigs_path = contigs_file
        self.name = "plasmids"
        self.out_files["short_plasmids"] = os.path.join(self.plasmids_dir,
                                                        "short_plasmids.fasta")

    def run(self):
        logger.info("Recovering plasmids")
        if not os.path.isdir(self.plasmids_dir):
            os.mkdir(self.plasmids_dir)
        short_plasmids = assemble_short_plasmids(self.args, self.plasmids_dir,
                                                 self.contigs_path)
        fp.write_fasta_dict(short_plasmids, self.out_files["short_plasmids"])
        logger.info("Added {0} extra contigs".format(len(short_plasmids)))
        #fp.write_fasta_dict(short_plasmids, self.contigs_path, "a")


class JobRepeat(Job):
    def __init__(self, args, work_dir, log_file, in_assembly):
        super(JobRepeat, self).__init__()

        self.args = args
        self.in_assembly = in_assembly
        self.log_file = log_file
        self.name = "repeat"

        self.repeat_dir = os.path.join(work_dir, "2-repeat")
        self.out_files["contigs"] = os.path.join(self.repeat_dir,
                                                 "graph_paths.fasta")
        self.out_files["assembly_graph"] = os.path.join(self.repeat_dir,
                                                        "graph_final.gv")
        self.out_files["edges_sequences"] = os.path.join(self.repeat_dir,
                                                         "graph_final.fasta")
        self.out_files["gfa_graph"] = os.path.join(self.repeat_dir,
                                                   "graph_final.gfa")
        self.out_files["stats"] = os.path.join(self.repeat_dir, "contigs_stats.txt")
        self.out_files["scaffold_links"] = os.path.join(self.repeat_dir,
                                                        "scaffolds_links.txt")

    def run(self):
        if not os.path.isdir(self.repeat_dir):
            os.mkdir(self.repeat_dir)
        logger.info("Performing repeat analysis")
        repeat.analyse_repeats(self.args, Job.run_params, self.in_assembly,
                               self.repeat_dir, self.log_file,
                               self.args.asm_config)


class JobFinalize(Job):
    def __init__(self, args, work_dir, log_file,
                 contigs_file, graph_file, repeat_stats,
                 polished_stats, polished_gfa, scaffold_links):
        super(JobFinalize, self).__init__()

        self.args = args
        self.log_file = log_file
        self.name = "finalize"
        self.contigs_file = contigs_file
        self.graph_file = graph_file
        self.repeat_stats = repeat_stats
        self.polished_stats = polished_stats
        self.scaffold_links = scaffold_links
        self.polished_gfa = polished_gfa

        #self.out_files["contigs"] = os.path.join(work_dir, "contigs.fasta")
        self.out_files["scaffolds"] = os.path.join(work_dir, "scaffolds.fasta")
        self.out_files["stats"] = os.path.join(work_dir, "assembly_info.txt")
        self.out_files["graph"] = os.path.join(work_dir, "assembly_graph.gv")
        self.out_files["gfa"] = os.path.join(work_dir, "assembly_graph.gfa")

    def run(self):
        #shutil.copy2(self.contigs_file, self.out_files["contigs"])
        shutil.copy2(self.graph_file, self.out_files["graph"])
        shutil.copy2(self.polished_gfa, self.out_files["gfa"])

        scaffolds = scf.generate_scaffolds(self.contigs_file, self.scaffold_links,
                                           self.out_files["scaffolds"])
        scf.generate_stats(self.repeat_stats, self.polished_stats, scaffolds,
                           self.out_files["stats"])

        logger.info("Final assembly: {0}".format(self.out_files["scaffolds"]))


class JobConsensus(Job):
    def __init__(self, args, work_dir, in_contigs):
        super(JobConsensus, self).__init__()

        self.args = args
        self.in_contigs = in_contigs
        self.consensus_dir = os.path.join(work_dir, "1-consensus")
        self.out_consensus = os.path.join(self.consensus_dir, "consensus.fasta")
        self.name = "consensus"
        self.out_files["consensus"] = self.out_consensus

    def run(self):
        if not os.path.isdir(self.consensus_dir):
            os.mkdir(self.consensus_dir)

        logger.info("Running Minimap2")
        out_alignment = os.path.join(self.consensus_dir, "minimap.sam")
        aln.make_alignment(self.in_contigs, self.args.reads, self.args.threads,
                           self.consensus_dir, self.args.platform, out_alignment,
                           reference_mode=True, sam_output=True)

        contigs_info = aln.get_contigs_info(self.in_contigs)
        logger.info("Computing consensus")
        consensus_fasta = cons.get_consensus(out_alignment, self.in_contigs,
                                             contigs_info, self.args.threads,
                                             self.args.platform,
                                             cfg.vals["min_aln_rate"])
        fp.write_fasta_dict(consensus_fasta, self.out_consensus)


class JobPolishing(Job):
    def __init__(self, args, work_dir, log_file, in_contigs, in_graph_edges,
                 in_graph_gfa):
        super(JobPolishing, self).__init__()

        self.args = args
        self.log_file = log_file
        self.in_contigs = in_contigs
        self.in_graph_edges = in_graph_edges
        self.in_graph_gfa = in_graph_gfa
        self.polishing_dir = os.path.join(work_dir, "3-polishing")

        self.name = "polishing"
        final_conitgs = os.path.join(self.polishing_dir,
                                     "polished_{0}.fasta".format(args.num_iters))
        self.out_files["contigs"] = final_conitgs
        self.out_files["stats"] = os.path.join(self.polishing_dir,
                                               "contigs_stats.txt")
        self.out_files["polished_gfa"] = os.path.join(self.polishing_dir,
                                                      "polished_edges.gfa")

    def run(self):
        if not os.path.isdir(self.polishing_dir):
            os.mkdir(self.polishing_dir)

        pol.polish(self.in_contigs, self.args.reads, self.polishing_dir,
                   self.args.num_iters, self.args.threads, self.args.platform,
                   output_progress=True)

        polished_file = os.path.join(self.polishing_dir, "polished_{0}.fasta"
                                     .format(self.args.num_iters))
        pol.generate_polished_edges(self.in_graph_edges, self.in_graph_gfa,
                                    polished_file,
                                    self.polishing_dir, self.args.platform,
                                    self.args.threads)


def _create_job_list(args, work_dir, log_file):
    """
    Build pipeline as a list of consecutive jobs
    """
    jobs = []

    #Run configuration
    jobs.append(JobConfigure(args, work_dir))

    #Assembly job
    jobs.append(JobAssembly(args, work_dir, log_file))
    draft_assembly = jobs[-1].out_files["assembly"]

    #Consensus
    if args.read_type != "subasm":
        jobs.append(JobConsensus(args, work_dir, draft_assembly))
        draft_assembly = jobs[-1].out_files["consensus"]

    #Repeat analysis
    jobs.append(JobRepeat(args, work_dir, log_file, draft_assembly))
    raw_contigs = jobs[-1].out_files["contigs"]
    scaffold_links = jobs[-1].out_files["scaffold_links"]
    graph_file = jobs[-1].out_files["assembly_graph"]
    gfa_file = jobs[-1].out_files["gfa_graph"]
    edges_seqs = jobs[-1].out_files["edges_sequences"]
    repeat_stats = jobs[-1].out_files["stats"]

    #Short plasmids
    jobs.append(JobShortPlasmidsAssembly(args, work_dir, raw_contigs))

    #Polishing
    contigs_file = raw_contigs
    polished_stats = None
    polished_gfa = gfa_file
    if args.num_iters > 0:
        jobs.append(JobPolishing(args, work_dir, log_file, raw_contigs,
                                 edges_seqs, gfa_file))
        contigs_file = jobs[-1].out_files["contigs"]
        polished_stats = jobs[-1].out_files["stats"]
        polished_gfa = jobs[-1].out_files["polished_gfa"]

    #Report results
    jobs.append(JobFinalize(args, work_dir, log_file, contigs_file,
                            graph_file, repeat_stats, polished_stats,
                            polished_gfa, scaffold_links))

    return jobs


def _set_kmer_size(args):
    if args.genome_size.isdigit():
        args.genome_size = int(args.genome_size)
    else:
        args.genome_size = human2bytes(args.genome_size.upper())


def _run(args):
    """
    Runs the pipeline
    """
    logger.info("Running Flye " + _version())
    logger.debug("Cmd: {0}".format(" ".join(sys.argv)))

    for read_file in args.reads:
        if not os.path.exists(read_file):
            raise ResumeException("Can't open " + read_file)

    save_file = os.path.join(args.out_dir, "params.json")
    jobs = _create_job_list(args, args.out_dir, args.log_file)

    current_job = 0
    if args.resume or args.resume_from:
        if not os.path.exists(save_file):
            raise ResumeException("Can't find save file")

        logger.info("Resuming previous run")
        if args.resume_from:
            job_to_resume = args.resume_from
        else:
            job_to_resume = json.load(open(save_file, "r"))["stage_name"]

        can_resume = False
        for i in xrange(len(jobs)):
            if jobs[i].name == job_to_resume:
                jobs[i].load(save_file)
                current_job = i
                if not jobs[i - 1].completed(save_file):
                    raise ResumeException("Can't resume: stage '{0}' incomplete"
                                          .format(jobs[i - 1].name))
                can_resume = True
                break

        if not can_resume:
            raise ResumeException("Can't resume: stage {0} does not exist"
                                  .format(job_to_resume))

    for i in xrange(current_job, len(jobs)):
        jobs[i].save(save_file)
        jobs[i].run()


def _enable_logging(log_file, debug, overwrite):
    """
    Turns on logging, sets debug levels and assigns a log file
    """
    log_formatter = logging.Formatter("[%(asctime)s] %(name)s: %(levelname)s: "
                                      "%(message)s", "%Y-%m-%d %H:%M:%S")
    console_formatter = logging.Formatter("[%(asctime)s] %(levelname)s: "
                                          "%(message)s", "%Y-%m-%d %H:%M:%S")
    console_log = logging.StreamHandler()
    console_log.setFormatter(console_formatter)
    if not debug:
        console_log.setLevel(logging.INFO)

    if overwrite:
        open(log_file, "w").close()
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(log_formatter)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_log)
    logger.addHandler(file_handler)


def _usage():
    return ("flye (--pacbio-raw | --pacbio-corr | --nano-raw |\n"
            "\t     --nano-corr | --subassemblies) file1 [file_2 ...]\n"
            "\t     --genome-size SIZE --out-dir PATH\n"
            "\t     [--threads int] [--iterations int] [--min-overlap int]\n"
            "\t     [--debug] [--version] [--help] [--resume]")


def _epilog():
    return ("Input reads could be in FASTA or FASTQ format, uncompressed\n"
            "or compressed with gz. Currenlty, raw and corrected reads\n"
            "from PacBio and ONT are supported. The expected error rates are\n"
            "<30% for raw and <2% for corrected reads. Additionally,\n"
            "--subassemblies option performs a consensus assembly of multiple\n"
            "sets of high-quality contigs. You may specify multiple\n"
            "files with reads (separated by spaces). Mixing different read\n"
            "types is not yet supported.\n\n"
            "You must provide an estimate of the genome size as input,\n"
            "which is used for solid k-mers selection. Standard size\n"
            "modificators are supported (e.g. 5m or 2.6g)\n\n"
            "To reduce memory consumption for large genome assemblies,\n"
            "you can use a subset of the longest reads for initial contig\n"
            "assembly by specifying --asm-coverage option. Typically,\n"
            "40x coverage is enough to produce good draft contigs.")


def _version():
    repo_root = os.path.dirname((os.path.dirname(__file__)))
    try:
        git_label = subprocess.check_output(["git", "-C", repo_root, "describe"],
                                            stderr=open(os.devnull, "w"))
        commit_id = git_label.strip("\n").rsplit("-", 1)[-1]
        return __version__ + "-" + commit_id
    except (subprocess.CalledProcessError, OSError):
        pass
    return __version__ + "-release"


def main():
    def check_int_range(value, min_val, max_val, require_odd=False):
        ival = int(value)
        if ival < min_val or ival > max_val:
             raise argparse.ArgumentTypeError("value should be in "
                            "range [{0}, {1}]".format(min_val, max_val))
        if require_odd and ival % 2 == 0:
            raise argparse.ArgumentTypeError("should be an odd number")
        return ival

    parser = argparse.ArgumentParser \
        (description="Assembly of long and error-prone reads",
         formatter_class=argparse.RawDescriptionHelpFormatter,
         usage=_usage(), epilog=_epilog())

    read_group = parser.add_mutually_exclusive_group(required=True)
    read_group.add_argument("--pacbio-raw", dest="pacbio_raw",
                        default=None, metavar="path", nargs="+",
                        help="PacBio raw reads")
    read_group.add_argument("--pacbio-corr", dest="pacbio_corrected",
                        default=None, metavar="path", nargs="+",
                        help="PacBio corrected reads")
    read_group.add_argument("--nano-raw", dest="nano_raw", nargs="+",
                        default=None, metavar="path",
                        help="ONT raw reads")
    read_group.add_argument("--nano-corr", dest="nano_corrected", nargs="+",
                        default=None, metavar="path",
                        help="ONT corrected reads")
    read_group.add_argument("--subassemblies", dest="subassemblies", nargs="+",
                        default=None, metavar="path",
                        help="high-quality contigs input")

    parser.add_argument("-g", "--genome-size", dest="genome_size",
                        metavar="size", required=True,
                        help="estimated genome size (for example, 5m or 2.6g)")
    parser.add_argument("-o", "--out-dir", dest="out_dir",
                        default=None, required=True,
                        metavar="path", help="Output directory")

    parser.add_argument("-t", "--threads", dest="threads",
                        type=lambda v: check_int_range(v, 1, 128),
                        default=1, metavar="int", help="number of parallel threads [1]")
    parser.add_argument("-i", "--iterations", dest="num_iters",
                        type=lambda v: check_int_range(v, 0, 10),
                        default=1, help="number of polishing iterations [1]",
                        metavar="int")
    parser.add_argument("-m", "--min-overlap", dest="min_overlap", metavar="int",
                        type=lambda v: check_int_range(v, 1000, 10000),
                        default=None, help="minimum overlap between reads [auto]")
    parser.add_argument("--asm-coverage", dest="asm_coverage", metavar="int",
                        default=None, help="reduced coverage for initial "
                        "contig assembly [not set]", type=int)

    parser.add_argument("--resume", action="store_true",
                        dest="resume", default=False,
                        help="resume from the last completed stage")
    parser.add_argument("--resume-from", dest="resume_from", metavar="stage_name",
                        default=None, help="resume from a custom stage")
    #parser.add_argument("--kmer-size", dest="kmer_size",
    #                    type=lambda v: check_int_range(v, 11, 31, require_odd=True),
    #                    default=None, help="kmer size (default: auto)")
    parser.add_argument("--debug", action="store_true",
                        dest="debug", default=False,
                        help="enable debug output")
    parser.add_argument("-v", "--version", action="version", version=_version())
    args = parser.parse_args()

    if args.pacbio_raw:
        args.reads = args.pacbio_raw
        args.platform = "pacbio"
        args.read_type = "raw"
    if args.pacbio_corrected:
        args.reads = args.pacbio_corrected
        args.platform = "pacbio"
        args.read_type = "corrected"
    if args.nano_raw:
        args.reads = args.nano_raw
        args.platform = "nano"
        args.read_type = "raw"
    if args.nano_corrected:
        args.reads = args.nano_corrected
        args.platform = "nano"
        args.read_type = "corrected"
    if args.subassemblies:
        args.reads = args.subassemblies
        args.platform = "subasm"
        args.read_type = "subasm"

    if not os.path.isdir(args.out_dir):
        os.mkdir(args.out_dir)
    args.out_dir = os.path.abspath(args.out_dir)

    args.log_file = os.path.join(args.out_dir, "flye.log")
    _enable_logging(args.log_file, args.debug,
                    overwrite=False)

    _set_kmer_size(args)
    args.asm_config = os.path.join(cfg.vals["pkg_root"],
                                   cfg.vals["bin_cfg"][args.read_type])

    try:
        aln.check_binaries()
        pol.check_binaries()
        asm.check_binaries()
        repeat.check_binaries()
        _run(args)
    except (aln.AlignmentException, pol.PolishException,
            asm.AssembleException, repeat.RepeatException,
            ResumeException) as e:
        logger.error(e)
        return 1

    return 0
