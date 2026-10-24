import os
from glob import glob

from setuptools import setup

package_name = 'app_gnss'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Taha Mohammed',
    maintainer_email='taha.mousa2023@gmail.com',
    description='GNSS/RTK integration for the BEARS rover',
    license='MIT',
    entry_points={'console_scripts': []},
)
