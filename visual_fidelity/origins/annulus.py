"""Software projection and shading for a bevelled annulus with an editable path."""
import cv2
import numpy as np

# Cross-section of the band, in radial and axial coordinates.
PROFILE = np.asarray([[-.68,-1],[.68,-1],[1,-.68],[1,.68],
                      [.68,1],[-.68,1],[-1,.68],[-1,-.68]])
LIGHT = np.array([-.45,-.53,.72])
LIGHT /= np.linalg.norm(LIGHT)
VIEW = np.array([0,0,1])
HALF = LIGHT + VIEW
HALF /= np.linalg.norm(HALF)
ALBEDO = np.array([226,139,57], dtype='float32')


def band_mesh(pose, thickness, axial, depth, arc, polarity=1, profile=PROFILE):
    x,y,major,minor,rotation = map(float,pose[:5])
    az = np.deg2rad(rotation)
    ratio = np.clip(minor/major,.02,1)
    u = np.array([np.cos(az),np.sin(az),0])
    v = np.array([-np.sin(az)*ratio,np.cos(az)*ratio,polarity*np.sqrt(1-ratio**2)])
    normal = np.cross(u,v)
    start,end = arc
    theta = np.linspace(start,end,max(6,round(120*(end-start)/(2*np.pi))))
    radial = np.cos(theta[:,None])*u + np.sin(theta[:,None])*v
    center = np.array([x,y,depth]) + major * radial
    vertices = (center[:,None,:] + radial[:,None,:]*profile[None,:,0,None]*thickness
                + normal[None,None,:]*profile[None,:,1,None]*axial)
    shifted = np.roll(vertices,-1,axis=1)
    quads = np.stack((vertices[:-1], vertices[1:], shifted[1:], shifted[:-1]),axis=-2)
    # Derive a smooth radial orientation and the flat profile normals separately.
    tangent = np.roll(profile,-1,axis=0)-profile
    profile_normals = np.stack((tangent[:,1]/axial, -tangent[:,0]/thickness),axis=1)
    mean_radial = (radial[:-1]+radial[1:])/2
    face_normals = (mean_radial[:,None,:]*profile_normals[None,:,0,None] +
                    normal[None,None,:]*profile_normals[None,:,1,None])
    face_normals /= np.linalg.norm(face_normals,axis=2,keepdims=True)
    if end-start < 6.27:
        # Use degenerate quads as triangles to cap both ends of open bands.
        caps=[]
        normals=[]
        for index,sign in [(0,-1),(-1,1)]:
            edge=vertices[index]
            cap=np.stack((edge,np.roll(edge,-1,axis=0),
                          np.tile(center[index],(len(edge),1)),
                          np.tile(center[index],(len(edge),1))),axis=1)
            caps.append(cap)
            tangent=-np.sin(theta[index])*u + np.cos(theta[index])*v
            normals.append(np.tile(tangent*sign,(len(edge),1)))
        return (np.concatenate((quads.reshape(-1,4,3),*caps)),
                np.concatenate((face_normals.reshape(-1,3),*normals)))
    return quads.reshape(-1,4,3),face_normals.reshape(-1,3)


def paint_bands(canvas, bands, *, albedo=ALBEDO, edge=(45,144,157), bloom=(16,11,5)):
    if not bands:
        return
    triangles, normals = (np.concatenate(items) for items in zip(*bands))
    visible = normals[:,2] > -.035
    triangles,normals = triangles[visible],normals[visible]
    x,y = triangles[...,0],triangles[...,1]
    z = triangles[...,2]
    perspective = 1 + (z - z.mean(axis=1,keepdims=True))*.00042
    # Near-orthographic camera retains the measured on-screen trajectories.
    points = np.stack((90+(x-90)*perspective,160+(y-160)*perspective),axis=-1)
    brightness = np.clip(normals @ LIGHT,0,1)
    specular = .57*np.maximum(normals @ HALF,0)**12
    grazing = .16*(1-np.clip(normals[:,2],0,1))**2
    color = np.asarray(albedo)*(.79+.26*brightness[:,None])
    color += (specular+grazing)[:,None]*np.asarray(edge)
    encoded = np.rint(np.clip(color,0,255)).astype('int')
    raster = np.zeros(canvas.shape,dtype='uint8')
    polygons = np.rint(points * 4 * 16).astype('int32')
    for face in np.argsort(z.mean(axis=1)):
        cv2.fillConvexPoly(raster, polygons[face], tuple(map(int,encoded[face])),
                           cv2.LINE_AA, shift=4)
    alpha = (raster.max(axis=2) > 0).astype('float32')[...,None]
    haze = cv2.GaussianBlur(raster[:,:,0], (0,0), 10).astype('float32')/255
    canvas[:] = canvas*(1-alpha) + raster
    canvas[:] += haze[...,None]*np.asarray(bloom,dtype='float32')
