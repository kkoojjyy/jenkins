#!/usr/bin/python

import xml.etree.ElementTree as ET
import os
import sys
from glob import glob

os.chdir("new_xmls")

publish_jobs = glob("*publish-rpms_nightly")

for job in publish_jobs:
    tree = ET.parse(job)
    root = tree.getroot()

    file_list = os.listdir(".")
    for child in root:
        if child.tag == 'builders':
            for project in child.iter('project'):
                if project.text in file_list:
                    print "job %s still exists" % project.text
                else:
                    sys.exit("job %s does not exists" % project.text)
            break
