from setuptools import setup
from glob import glob
import os

package_name = 'app_fast_livo2'

setup(
    name=package_name,
    version='0.0.1',
    packages=[],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Paul',
    maintainer_email='p.david@campus.tu-berlin.de',
    description='Composable-node launch tying ZED2i + Ouster + FAST-LIVO2 into one container',
    license='MIT',
    entry_points={},
)
