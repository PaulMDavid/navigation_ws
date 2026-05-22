from setuptools import setup, find_packages
from glob import glob
import os

package_name = 'app_microstrain'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Paul Mangalam, Taha',
    maintainer_email='p.david@campus.tu-berlin.de',
    description='Microstrain Imu package',
    license='MIT',
    entry_points={
        'console_scripts': [],
    },
)