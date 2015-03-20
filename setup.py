from setuptools import setup, find_packages

setup(
    name='bake',
    version='2.0',
    description='A project scripting and build utility.',
    long_description=open('README.rst').read(),
    license='BSD',
    author='Jordan McCoy',
    author_email='mccoy.jordan@gmail.com',
    url='https://github.com/arterial-io/bake',
    install_requires=[
        'scheme>=2',
        'PyYaml>=3',
        'colorama',
    ],
    packages=find_packages(exclude=['docs', 'tests']),
    entry_points={
        'console_scripts': [
            'bake = bake.runtime:run',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Utilities',
    ]
)
