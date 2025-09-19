import pybullet as p, pybullet_data
URDF = r'D:\RELOJ_2\Reloj_2\robot_reloj\Robot Virtual\Robot Virtual\urdf\Reloj_1_resuelto.urdf'
print('using', URDF)
cid = p.connect(p.DIRECT)
p.setAdditionalSearchPath(pybullet_data.getDataPath())
p.setAdditionalSearchPath(r'D:\RELOJ_2\Reloj_2\robot_reloj\Robot Virtual\Robot Virtual')
p.setAdditionalSearchPath(r'D:\RELOJ_2\Reloj_2\robot_reloj\Robot Virtual\Robot Virtual\meshes')
try:
    rid = p.loadURDF(URDF, [0,0,0.01], useFixedBase=True)
    print('loaded rid', rid)
except Exception as e:
    print('load exception', e)
