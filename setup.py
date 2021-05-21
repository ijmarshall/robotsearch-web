from setuptools import setup, find_packages

install_requires = ['scipy==0.19.1',
					'numpy==1.15.2',
					'tensorflow==2.5.0',
					'scikit_learn==0.19.1',
					'Keras==2.0.6',
					'h5py==2.7.1']

setup(name='robotsearch',
      author='Iain Marshall',
      author_email="mail@ijmarshall.com",
      version='0.1.3',
      install_requires=install_requires,
      entry_points = {
    	'console_scripts': [
        'robotsearch = robotsearch.__main__:main',
    	]},
      package_data={'robotsearch': ['data/rct/*.*']},
      packages=find_packages(),
)
