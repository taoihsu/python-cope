#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2015 Huy Nguyen <huy.nguyendinh09@gmail.com>
#
# This file is part of python-cope.
#
# python-cope is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# python-cope is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# python-cope. If not, see <http://www.gnu.org/licenses/>.

import numpy  as np
import trimesh as trm
import scipy as sp
import SE3UncertaintyLib as SE3lib
import bisect
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
import time
import copy
import IPython

def VisualizeParticles(list_particles,weights,env='',body ='', showestimated = False):
  maxweight = 0
  for w in weights:
    if w > maxweight:
      maxweight = w    
  if showestimated is False:
    weight_threshold = 0.7*maxweight
    from openravepy import RaveCreateKinBody
    with env:
      env.Reset()
      newbodies = []
      for i in range(len(list_particles)):
        if weights[i] > weight_threshold:
          p = list_particles[i]
          transparency = 0#1 - weights[i]/maxweight
          transf = p
          newbody = RaveCreateKinBody(env,body.GetXMLId())
          newbody.Clone(body,0)
          newbody.SetName(body.GetName())
          for link in newbody.GetLinks():
            for geom in link.GetGeometries():
              geom.SetTransparency(transparency)
              geom.SetDiffuseColor([0.64,0.35,0.14])
              env.AddKinBody(newbody,True)
          with env:
            newbody.SetTransform(transf)

          newbodies.append(newbody)
  else:
    acum_weight = 0
    acum_tf = np.zeros((4,4))
    weight_threshold = 0.7*maxweight
    for i in range(len(list_particles)):
      if weights[i] > weight_threshold:
        p = list_particles[i]
        acum_tf += p*weights[i]
        acum_weight += weights[i]
    estimated_particle = acum_tf*(1/acum_weight)
    transf = estimated_particle
    print "Resulting estimation:\n", transf
    body.SetTransform(transf)
    env.AddKinBody(body,True)
    return transf


class Region(object):
  def __init__(self, particles, delta_rot,delta_trans):
    self.particles = particles #List of particles (transformations)
    self.delta_rot = delta_rot
    self.delta_trans = delta_trans

def IsInside(point,center,radius):
  if np.linalg.norm(point-center) < radius:
    return True
  return False


def EvenDensityCover(region, M):
  '''Input: Region V_n - sampling region represented as a union of neighborhoods, M - number of particles to sample per neighborhood
  Output: a set of particles that evenly cover the region (the new spheres will have analogous shape to the region sigma)
  '''
  particles = []
  num_spheres = len(region.particles)
  delta_rot = region.delta_rot
  delta_trans = region.delta_trans
  for i  in range(num_spheres):
    center_particle = region.particles[i]
    center_vec_rot =  SE3lib.RotToVec(center_particle[:3,:3])
    center_vec_trans = center_particle[:3,3]
    num_existing = 0
    for p in particles:
      if IsInside(SE3lib.RotToVec(p[:3,:3]),center_vec_rot,delta_rot) and IsInside(p[:3,3],center_vec_trans,delta_trans):
        num_existing += 1
    for m in range(M-num_existing):
      count = 0
      accepted = False
      while not accepted and count < 5:
        new_vec_rot = np.random.uniform(-1,1,size = 3)*delta_rot + center_vec_rot
        new_vec_trans = np.random.uniform(-1,1,size = 3)*delta_trans + center_vec_trans
        count += 1
        accepted = True
        for k in range(i-1):
          previous_center = region.particles[k]
          previous_vec_rot = SE3lib.RotToVec(previous_center[:3,:3])
          previous_vec_trans = previous_center[:3,3]
          if IsInside(SE3lib.RotToVec(p[:3,:3]),previous_vec_rot,delta_rot) and IsInside(p[:3,3],previous_vec_trans,delta_trans):
            accepted = False
            break
      if accepted:
        new_p = np.eye(4)
        new_p[:3,:3] = SE3lib.VecToRot(new_vec_rot)
        new_p[:3,3] = new_vec_trans
        particles.append(new_p)
    # IPython.embed()
  return particles

class Mesh(object):
  def __init__(self, obj): #trimesh obj
    self.vertices = obj.vertices 
    self.faces = obj.faces
    self.normals = obj.face_normals
    self.facets = obj.facets

def ComputeNormalizedWeights(mesh, particles,measurements,tau):
  num_particles = len(particles)
  new_weights = np.zeros(num_particles)
  for i in range(len(particles)):
    T = np.linalg.inv(particles[i])
    D = copy.deepcopy(measurements)
    for d in D:
      d[0] = np.dot(T[:3,:3],d[0]) + T[:3,3]
      d[1] = np.dot(T[:3,:3],d[1])
    total_energy = sum([CalculateMahaDistanceMesh_old(mesh,d)**2 for d in D])
    new_weights[i] = (np.exp(-0.5*total_energy/tau))
  return normalize(new_weights)

def normalize(weights):
  norm_weights = np.zeros(len(weights))
  sum_weights = np.sum(weights)
  for i in range(len(weights)):
    norm_weights[i] = weights[i]/sum_weights
  return norm_weights

def CalculateMahaDistanceFace(face,d,i):
  '''
  :param face:     Vector [p1,p2,p3]: three points of a face
  :param d:           Measurement data [p,n,o_n,o_p]: measurement point and vector
  :return:
  '''
  p1,p2,p3,v = face
  p,n,o_p,o_n = d
  n = -n # reverse normal of the measurement
  # v = v # reverse normal of the face
  # Get distance to surface
  norm = lambda x: np.linalg.norm(x)
  inner = lambda a, b: np.inner(a,b)
  diff_distance   = norm(inner((p-p1), v)/norm(v))
  # Get differences in normal direction
  diff_angle      = np.arccos(inner(v, n)/norm(v)/norm(n))
  # Maha distance
  ans = np.sqrt(diff_distance**2/o_p**2+diff_angle**2/o_n**2)
  return ans

def CalculateMahaDistanceMesh(mesh,d):
  '''
  :param  mesh:       A sorted mesh
  :param  d   :       A measurement [p,n,o_n,o_p]
  '''
  # IPython.embed()
  dis = []
  ref_axis = mesh[2]
  d_normal = -d[1]
  angle = np.arccos(np.dot(d_normal,ref_axis))
  x = [r[2] for r in mesh[0]]
  delta_angle = mesh[3]/2.
  # IPython.embed()
  up_bound = bisect.bisect_right(x,angle+delta_angle)
  low_bound = bisect.bisect_left(x[:up_bound],angle-delta_angle)
  for i in range(up_bound-low_bound):
    # print i, angle, low_bound, up_bound, mesh[0][i][
    # print d_normal,mesh[0][i][1]
    A,B,C = mesh[0][i][0]
    # IPython.embed()
    dis.append(CalculateMahaDistanceFace([mesh[1][A],mesh[1][B],mesh[1][C],mesh[0][i][1]],d,i))
  return min(dis)

def CalculateMahaDistanceMesh_old(mesh,d):
  '''
  :param  mesh:       A trimesh object
  :param  d   :       A measurement [p,n,o_n,o_p]
  '''
  dis = [ ]
  for i in range(len(mesh[0])):
    A,B,C = mesh[0][i][0]
    dis.append(CalculateMahaDistanceFace([A,B,C,mesh[0][i][1]],d,i))
  return min(dis)


def Pruning(list_particles, weights,percentage):
  assert (len(list_particles)==len(weights)),"Wrong input data, length of list of particles are not equal to length of weight"
  num_particles = len(list_particles)
  pruned_list = []
  new_list_p = []
  new_list_w = []
  c = np.zeros(num_particles)
  c[0] = weights[0]
  for i in range(num_particles-1):
    c[i+1] = c[i] + weights[i+1]
  u = np.zeros(num_particles)
  u[0] = np.random.uniform(0,1)/num_particles
  k = 0
  for i in range(num_particles):
    u[i] = u[0] + 1./num_particles*i
    while (u[i] > c[k]):
      k+=1
    new_list_p.append(list_particles[k]) 
  for i in range(num_particles):
    if i == 0:
      pruned_list.append(new_list_p[i])
    else:
      if not np.allclose(np.dot(new_list_p[i],np.linalg.inv(new_list_p[i-1])),np.eye(4)):
        # IPython.embed()
        pruned_list.append(new_list_p[i])
  return pruned_list
      
    
def SameTransformations(T1,T2,rot_tol,trans_tol):
  return True

def Pruning_old(list_particles, weights,prune_percentage):
  assert (len(list_particles)==len(weights)),"Wrong input data, length of list of particles are not equal to length of weight"
  pruned_list = []
  maxweight = 0
  for w in weights:
    if w > maxweight:
      maxweight = w
  threshold = prune_percentage*maxweight
  for i in range(len(list_particles)):
    if weights[i] > threshold:
      pruned_list.append(list_particles[i])
  return pruned_list

def Visualize(mesh,list_particles=[],D=[]):
  show_ = mesh.copy()
  show_.apply_transform(list_particles[-1])
  color = np.array([  21, 51,  252, 255])
  for face in mesh.faces:
    mesh.visual.face_colors[face] = color
  for d in D:
    sphere = trm.creation.icosphere(3,0.0025)
    TF = np.eye(4)
    TF[:3,3] = d[0]
    TF2 = np.eye(4)
    angle = np.arccos(np.dot(d[1],np.array([0,0,1])))
    vec = np.cross(d[1],np.array([0,0,1]))
    TF2[:3,:3] = SE3lib.VecToRot(angle*vec)
    TF2[:3,3] = d[0] + np.dot(SE3lib.VecToRot(angle*vec),np.array([0,0,0.1/2.]))
    cyl = trm.creation.cylinder(0.001,0.1)
    cyl.apply_transform(TF2)
    show_ += cyl
    sphere.apply_transform(TF)
    show_ += sphere
  for z in range(len(list_particles)-1):
    new_mesh = mesh.copy()
    new_mesh.apply_transform(list_particles[z])
    show_ += new_mesh
  show_.show()
  return True

def Volume(radius,dim):
  return (np.pi**(dim/2.))/sp.special.gamma(dim/2.+1)*(radius**dim)

def ScalingSeries(sorted_mesh, visualize_mesh, particles0, D, M, sigma0, sigma_desired, prune_percentage =0.6,dim = 6, visualize = False):
  """
  @type  V0:  ParticleFilterLib.Region
  @param V0:  initial uncertainty region
  @param  D:  a list of measurements [p,n,o_n,o_p] p is the contacted point, n is the approaching vector (opposite to normal)
  @param  M:  the no. of particles per neighborhood
  @param delta_desired: terminal value of delta
  @param dim: dimension of the state space (6 DOFs)
  """ 
  zoom = 2**(-1./6.)
  delta_rot = np.max(np.linalg.cholesky(sigma0[3:,3:]).T)
  delta_trans = np.max(np.linalg.cholesky(sigma0[:3,:3]).T)
  delta_desired_rot = np.max(np.linalg.cholesky(sigma_desired[3:,3:]).T)
  delta_desired_trans = np.max(np.linalg.cholesky(sigma_desired[:3,:3]).T)
  # print delta_rot
  # print delta_trans
  # print delta_desired_rot
  # print delta_desired_trans
  # raw_input()
  N_rot  = np.log2(Volume(delta_rot,3)/Volume(delta_desired_rot,3))
  N_trans = np.log2(Volume(delta_trans,3)/Volume(delta_desired_trans,3))
  N = int(np.round(max(N_rot,N_trans)))
  # IPython.embed()
  # N = int(np.round(np.log2(volume_0/volume_desired)))
  print N
  particles = particles0
  V = Region(particles,delta_rot,delta_trans)
  t1 = 0.
  t2 = 0.
  t3 = 0.
  for n in range(N):
    print N-n
    delta_rot = delta_rot*zoom
    delta_trans = delta_trans*zoom
    tau = (delta_trans/delta_desired_trans)**(1./1.)
    
    # Sample new set of particles based on from previous region and M
    t0 = time.time()
    particles = EvenDensityCover(V,M)
    print "len of new generated particles ", len(particles)
    print 'tau ', tau
    t1 += time.time() - t0
    t0 = time.time()
    # Compute normalized weights
    weights = ComputeNormalizedWeights(sorted_mesh, particles, D, tau)
    # print "weights after normalizing",  weights
    t2 += time.time() - t0 
    t0 = time.time()
    # Prune based on weights
    pruned_particles = Pruning_old(particles,weights,prune_percentage)
    t3 += time.time() - t0     
    print 'No. of particles, after pruning:', len(pruned_particles)
    # Create a new region from the set of particle left after pruning
    V = Region(pruned_particles,delta_rot,delta_trans)
    if visualize:
      Visualize(visualize_mesh,particles,D)
    # raw_input()
    # print "delta_prv",  sigma
  print 't1 _ EVEN density', t1
  print 't2 _ UPDATE probability', t2
  print 't3 _ PRUNE particles', t3
  new_set_of_particles = EvenDensityCover(V,M)
  new_weights = ComputeNormalizedWeights(sorted_mesh, new_set_of_particles,D,1.0)
  return new_set_of_particles, new_weights