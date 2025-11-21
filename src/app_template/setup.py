from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'app_template'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Paul Mangalam',
    maintainer_email='p.david@campus.tu-berlin.de',
    description='Template navigation package',
    license='I have no clue, sorry',
    entry_points={
        'console_scripts': [
            'template_node = app_template.template_node:main',
        ],
    },
)
