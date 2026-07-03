from setuptools import setup
from glob import glob
import os

package_name = 'app_rtab_zed2i'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Patrick',
    maintainer_email='patrick.ugwu@campus.tu-berlin.de',
    description='Combined RTABmap + ZED2i composable launch',
    license='MIT',
    entry_points={},
)