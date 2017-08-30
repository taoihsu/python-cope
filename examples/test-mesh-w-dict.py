import trimesh
import numpy as np
import scipy as sp
import bisect
import SE3UncertaintyLib as SE3
import transformation as tr
import pickle
import copy
import IPython

def generate_measurements(mesh,tranformation,pos_err,nor_err,num_measurements):
  ## Generate random points on obj surfaces
  # For individual triangle sampling uses this method:
  # http://mathworld.wolfram.com/TrianglePointPicking.html

  # len(mesh.faces) float array of the areas of each face of the mesh
  area = mesh.area_faces
  # total area (float)
  area_sum = np.sum(area)
  # cumulative area (len(mesh.faces))
  area_cum = np.cumsum(area)
  face_pick = np.random.random(num_measurements)*area_sum
  face_index = np.searchsorted(area_cum, face_pick)
  # pull triangles into the form of an origin + 2 vectors
  tri_origins = mesh.triangles[:, 0]
  tri_vectors = mesh.triangles[:, 1:].copy()
  tri_vectors -= np.tile(tri_origins, (1, 2)).reshape((-1, 2, 3))
  # pull the vectors for the faces we are going to sample from
  tri_origins = tri_origins[face_index]
  tri_vectors = tri_vectors[face_index]
  # randomly generate two 0-1 scalar components to multiply edge vectors by
  random_lengths = np.random.random((len(tri_vectors), 2, 1))
  # points will be distributed on a quadrilateral if we use 2 0-1 samples
  # if the two scalar components sum less than 1.0 the point will be
  # inside the triangle, so we find vectors longer than 1.0 and
  # transform them to be inside the triangle
  random_test = random_lengths.sum(axis=1).reshape(-1) > 1.0
  random_lengths[random_test] -= 1.0
  random_lengths = np.abs(random_lengths)
  # multiply triangle edge vectors by the random lengths and sum
  sample_vector = (tri_vectors * random_lengths).sum(axis=1)
  # finally, offset by the origin to generate
  # (n,3) points in space on the triangle
  samples = sample_vector + tri_origins
  normals = mesh.face_normals[face_index]

  ## Transform points and add noise
  # point_errs = np.random.multivariate_normal(np.zeros(3),np.eye(3),num_measurements)
  random_vecs = np.random.uniform(-1,1,(num_measurements,3))
  point_errs = np.asarray([np.random.normal(0.,np.sqrt(3)*pos_err)*random_vec/np.linalg.norm(random_vec) for random_vec in random_vecs])
  noisy_points = copy.deepcopy(samples) + point_errs


  noisy_normals = [np.dot(tr.rotation_matrix(np.random.normal(0.,nor_err),np.cross(np.random.uniform(-1,1,3),n))[:3,:3],n) for n in normals]
  noisy_normals = np.asarray([noisy_n/np.linalg.norm(noisy_n) for noisy_n in noisy_normals])

  dist = [np.linalg.norm(point_err) for point_err in point_errs]
  alpha = [np.arccos(np.dot(noisy_normals[i],normals[i])) for i in range(len(normals))]
## not correct alpha err!!
  # print np.sqrt(np.cov(dist))
  # print np.sqrt(np.cov(alpha))
  measurements = [[noisy_points[i],noisy_normals[i]] for i in range(num_measurements)]
  return measurements


pkl_file = open('mesh_w_dict.p', 'rb')
mesh_w_dict = pickle.load(pkl_file)
pkl_file.close()

mesh = trimesh.load_mesh('featuretype.STL')

# Measurements' Errs
pos_err = 2e-3
nor_err = 5./180.0*np.pi

num_measurements = 10
tranformation= np.eye(4)

measurements = generate_measurements(mesh,tranformation,pos_err,nor_err,num_measurements)


color = trimesh.visual.random_color()
for face in mesh.faces:
    mesh.visual.face_colors[face] = color

show = mesh.copy()
color = trimesh.visual.random_color()
for d in measurements:
  sphere = trimesh.creation.icosphere(3,0.01)
  TF = np.eye(4)
  TF[:3,3] = d[0]
  TF2 = np.eye(4)
  angle = np.arccos(np.dot(d[1],np.array([0,0,1])))
  vec = np.cross(d[1],np.array([0,0,1]))
  TF2[:3,:3] = SE3.VecToRot(angle*vec)
  TF2[:3,3] = d[0] + np.dot(SE3.VecToRot(angle*vec),np.array([0,0,0.1/2.]))
  cyl = trimesh.creation.cylinder(0.1,1)
  cyl.apply_transform(TF2)
  # show += cyl
  sphere.apply_transform(TF)
  show+=sphere
show.show()