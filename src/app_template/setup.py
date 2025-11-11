from setuptools import setup

package_name = 'app_template'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    py_modules=[
        'app_template.template_node',
    ],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name + '/launch', ['launch/template.launch.py']),
        ('share/' + package_name + '/config', ['config/params.yaml']),
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
