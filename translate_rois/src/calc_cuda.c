#include <THC/THC.h>
#include <math.h>
#include "calc_cuda_kernel.h"
#include <omp.h>
extern THCState *state;

/* int calc_test_cuda(int K, int N, float thresh, int array_size, THCudaTensor *pos, THCudaTensor *pos_indices, THCudaTensor * actioness, */
/* 		   THCudaTensor * overlaps_scr, THCudaTensor * scores, THCudaTensor * overlaps, int idx,  /\* return arrays *\/ */
/* 		   THCudaTensor * next_pos, THCudaTensor * next_pos_indices, THCudaTensor * next_actioness, */
/* 		   THCudaTensor * next_overlaps_scr, THCudaTensor * f_scores) */

/* int calc_test_cuda(int K, int N, float thresh, int array_size, THCudaIntTensor *pos, THCudaIntTensor *pos_indices, THCudaFloatTensor * actioness, */
/* 		   THCudaFloatTensor * overlaps_scr, THCudaFloatTensor * scores, THCudaFloatTensor * overlaps, int idx,  /\* return arrays *\/ */
/* 		   THCudaIntTensor * next_pos, THCudaIntTensor * next_pos_indices, THCudaFloatTensor * next_actioness, */
/* 		   THCudaFloatTensor * next_overlaps_scr, THCudaFloatTensor * f_scores) */

int calc_test_cuda(int K, int N, int n_frames, int n_combs, int sample_duration, int step, THCudaTensor * p_tubes, THCudaIntTensor * combinations, THCudaTensor *ret_tubes)
  

{
  int   * combinations_data    = THCudaIntTensor_data(state, combinations);

  float * p_tubes_data         = THCudaTensor_data(state, p_tubes);
  float * ret_tubes_data       = THCudaTensor_data(state, ret_tubes);

  cudaStream_t stream = THCState_getCurrentStream(state);

  CalculationLaucher(K, N, n_frames,n_combs, sample_duration, step, p_tubes_data, combinations_data, ret_tubes_data, stream);

  return 1;

}
