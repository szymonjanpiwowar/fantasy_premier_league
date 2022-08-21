from setuptools import setup

setup(name='fpl_mailbot',
      version='0.1',
      description='Mailbot support for a private FPL.',
      long_description='The mailbot created to send transfer deadline reminders and newsletter to '
                       'employees participating in a private classic FPL league.',
      classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9.7',
      ],
      keywords='Fantasy Premier League',
      url='https://github.com/szymonjanpiwowar/fantasy_premier_league',
      author='Szymon Jan Piwowar',
      author_email='szymonjanpiwowar@gmail.com',
      packages=['fpl_mailbot'],
      install_requires=[
          'pandas',
          'googleapiclient',
          'google_auth_oauthlib',
          'google'
      ],
      include_package_data=True,
      zip_safe=False
      )