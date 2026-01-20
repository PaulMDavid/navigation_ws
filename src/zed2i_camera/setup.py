from setuptools import setup, find_packages
from setuptools.command.install import install
import os
from glob import glob

package_name = 'zed2i_camera'

class CustomInstallCommand(install):
    def run(self):
        install.run(self)
        # Create lib directory structure for launch compatibility
        lib_dir = os.path.join(self.install_base, 'lib', package_name)
        os.makedirs(lib_dir, exist_ok=True)
        
        # Create symlink to executable if it exists
        bin_dir = os.path.join(self.install_base, 'bin')
        executable_path = os.path.join(bin_dir, 'zed2i_camera_node')
        symlink_path = os.path.join(lib_dir, 'zed2i_camera_node')
        
        if os.path.exists(executable_path) and not os.path.exists(symlink_path):
            os.symlink(os.path.relpath(executable_path, lib_dir), symlink_path)

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
    description='ZED 2i camera ROS2 node',
    license='I have no clue, sorry',
    entry_points={
        'console_scripts': [
            'zed2i_camera_node = zed2i_camera.zed2i_camera_node:main',
        ],
    },
    cmdclass={
        'install': CustomInstallCommand,
    },
)
