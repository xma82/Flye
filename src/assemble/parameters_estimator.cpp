//(c) 2016 by Authors
//This file is a part of ABruijn program.
//Released under the BSD license (see LICENSE file)

#include "parameters_estimator.h"
#include "../common/logger.h"


size_t ParametersEstimator::genomeSizeEstimate()
{
	return _takenKmers;
}


void ParametersEstimator::estimateMinKmerCount(int upperCutoff)
{
	const int MIN_CUTOFF = 2;

	size_t totalKmers = 0;
	for (auto mapPair = _vertexIndex.getKmerHist().rbegin();
		 mapPair != _vertexIndex.getKmerHist().rend(); ++mapPair)
	{
		totalKmers += mapPair->second;
	}
	size_t repeatKmerCount = totalKmers * 
							(float)Config::get("repeat_kmer_rate");
	
	size_t takenKmers = 0;
	size_t cutoff = 0;
	size_t repetitiveKmers = 0;
	size_t prevDiff = 0;
	for (auto mapPair = _vertexIndex.getKmerHist().rbegin();
		 mapPair != _vertexIndex.getKmerHist().rend(); ++mapPair)
	{
		if (repetitiveKmers < repeatKmerCount)
		{
			repetitiveKmers += mapPair->second;
		}
		else
		{
			if (_maxKmerCount == std::numeric_limits<size_t>::max())
			{
				_maxKmerCount = mapPair->first;
			}

			takenKmers += mapPair->second;
			if (takenKmers >= _genomeSize)
			{
				if (std::max(takenKmers, _genomeSize) - 
					std::min(takenKmers, _genomeSize) < prevDiff)
				{
					cutoff = mapPair->first;
				}
				else
				{
					cutoff = mapPair->first + 1;
					takenKmers -= mapPair->second;
				}
				break;
			}
			prevDiff = std::max(takenKmers, _genomeSize) - 
					   std::min(takenKmers, _genomeSize);
		}
	}

	if (cutoff < 2)
	{
		if ((bool)Config::get("low_cutoff_warning"))
		{
			Logger::get().warning() << "Unable to separate erroneous k-mers "
						  "from solid k-mers. Possible reasons: \n"
						  "\t(1) Incorrect expected assembly size parameter \n"
						  "\t(2) Highly uneven coverage of the assembly \n"
						  "\t(3) Running with error-corrected reads in raw reads mode\n"
						  "\tAssembly will continue, but results might not be optimal";
		}
		cutoff = MIN_CUTOFF;
	}
	
	Logger::get().debug() << "Filtered " << repetitiveKmers 
						  << " repetitive kmers";
	Logger::get().debug() << "Repetetive k-mer frequency: " << _maxKmerCount;
	Logger::get().debug() << "Estimated minimum kmer coverage: " << cutoff 
						  << ", " << takenKmers << " unique kmers selected";

	_takenKmers = takenKmers;
	_minKmerCount = cutoff;
}
