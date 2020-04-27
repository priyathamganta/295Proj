import os
import docker
import tarfile
import time
from io import BytesIO
import paramiko
import logging
import threading

logging.basicConfig(filename='deployment.log', filemode='w', level=logging.DEBUG,format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
hostname = "128.105.146.154"
username = "dharma"
password = ""
controller_ip = "155.98.37.91"
host_ip = "10.0.0.132"
i=0

#apiclient = docker.APIClient(base_url='tcp://10.0.0.132:2375',version="1.40")
#dockerClient = docker.DockerClient(base_url='tcp://10.0.0.132:2375',version="1.40")

def runSSH(host_ip,commands):
    # initialize the SSH client
    client = paramiko.SSHClient()
    logging.info("Getting Private token")
    k = paramiko.RSAKey.from_private_key_file("/usr/local/dharma")
    
    # add to known hosts
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logging.info("Initiating Conection")
        client.connect(hostname=host_ip, username=username, pkey = k)
        logging.info("Connection Successfull")
        #client.connect(hostname=host_ip, username="sdnnfv", password="1234")
    except:
        logging.info("[!] Cannot connect to the SSH Server")
        exit()
    # execute the commands
    for command in commands:
        logging.info(command)
        stdin, stdout, stderr = client.exec_command('sudo '+ command , get_pty=True)
        #stdin.write('1234\n')
        #stdin.flush()
        logging.info('Output is :%s',stdout.read().decode())
        err = stderr.read().decode()
        if err:
            logging.warning(err)
            return False
    return True

def runContainer(host_ip,switch_id,protocol):
    
def runContainer_thread(host_ip,switch_id,protocol):
    logging.info("Starting Deployment in switch : %s" , str(host_ip),)
    apiclient = docker.APIClient(base_url='tcp://' + host_ip +':2375',version="1.39")
    dockerClient = docker.DockerClient(base_url='tcp://' + host_ip +':2375',version="1.39")
    global i
    if i==0: 
        try:
            i = i+1
            container = dockerClient.containers.run('dharmadheeraj/sdnnfv',cap_add=['NET_ADMIN','NET_RAW'],detach=True,tty=True);
            logging.info("Container Deployed with id: %s" + container.id)
            runPigRelay(container)
            bridge_name = str(container.name)[:str(container.name).find('_')]
            logging.info('bridge Name : %s', bridge_name)
            logging.info("Adding Commands")
            commands = []
            commands.append('ovs-vsctl add-br ' + bridge_name)
            commands.append('ifconfig ' + bridge_name + ' up')
            commands.append('ovs-docker add-port '+ bridge_name +' eth1 ' + str(container.name))
            commands.append('ovs-docker add-port '+ bridge_name +' eth2 ' + str(container.name))
            commands.append('ip link add veth0 type veth peer name veth1')
            commands.append('ifconfig veth1 up')
            commands.append('ifconfig veth0 up')
            commands.append('ovs-vsctl add-port ' + bridge_name + ' veth1')
            commands.append('ovs-vsctl add-port ovs-lan veth0 -- set interface veth0 ofport_request=3')
            commands.append('ovs-ofctl add-flow ' + bridge_name + ' in_port=3,actions=output:1')
            commands.append('ovs-ofctl add-flow ' + bridge_name + ' in_port=2,actions=output:3')
            logging.info("Starting ssh commands")
            if runSSH(host_ip,commands):
                startSnort(container)
        
        
            return True
        
        except docker.errors.ContainerError:
            logging.warning("Error in container execution")
            return False;
    
        except docker.errors.ImageNotFound:
            if downloadImage(dockerClient,'dharmadheeraj/sdnnfv','latest'):
                runContainer(host_ip,switch_id,protocol)
            else:
                logging.warning("Error Downloading Image")
                return False
    
        except docker.errors.APIError:
            logging.warning("Connection to the docker Deamon not successful")
            return False
    else:
        logging.warning("Ignoring Docker Run")

def startSnort(container):
    try:
        logging.info("Runing snort in : %s",container.id)
        result = container.exec_run('sh -c \'snort -A unsock -l /tmp -c /etc/snort/snort.conf -Q -i eth1:eth2\'',stderr=True,stdout=True)
        logging.info("Finished Running snort with exit-code: %s" + str(result.exit_code))

        for line in result:
                logging.info('%s',line)
        return True
    except docker.errors.ContainerError:
        logging.warning("Error in container execution")
        return False;
    
def downloadImage(client,imageName,tag):
    try:
        print("="*25, "Downloading Docker Image ",imageName, "="*25)
        image = client.images.pull(repository=imageName,tag=tag)
        if image.id is not None:
            return True
    except docker.errors.ImageNotFound:
        print("Image Not found")
        return False
    except docker.errors.APIError:
        print("Connection to the docker Deamon not successful")
        return False

def runPigRelay(container):
    result = container.exec_run('sh -c "sed -i \'s/172.17.0.1/155.98.37.91/g\' pigrelay.py"')
    logging.info("Changed pigrelay file with error code:" + str(result.exit_code))
    result2 = container.exec_run('sh -c \'python pigrelay.py\'')
    logging.info("Started Pigrelay with exit code:" + str(result.exit_code))
    
def changeRules(filename,container):
    print("Changing Rules for container:" + container.id)
    tarFile = getTarFile(filename)
    copyFile(container,tarFile)
    
    
def getTarFile(fileName):
    allRules = 'These are my rules'
    print (allRules)
    #write password to file
    pw_tarstream = BytesIO()
    pw_tar = tarfile.TarFile(fileobj=pw_tarstream, mode='w')
    file_data = allRules.encode('utf8')
    tarinfo = tarfile.TarInfo(name=str(fileName) + '.rules')
    tarinfo.size = len(file_data)
    tarinfo.mtime = time.time()
    pw_tar.addfile(tarinfo, BytesIO(file_data))
    pw_tar.close()
    
    return pw_tarstream

def copyFile(container,tarFile):
    print("Copying file to container :" + container.id)
    tarFile.seek(0)
    copy = apiclient.put_archive(
        container=container.id,
        path='/etc/snort/rules',
        data=tarFile
        )

def stopSnort(container):
    stop = container.exec_run('sh -c "ps aux | awk {\'print $11 $2\'} | grep ^snort"' ,stderr=True,stdout=True,workdir="/")
    process_id = str(stop.output, 'utf-8')[5:]
    print("killing procces with id" + process_id)
    result = container.exec_run('sh -c "kill ' + process_id +'"',stderr=True,stdout=True)
    print(result)
    
    
#container = dockerClient.containers.get('strange_goldstine')

#bridge = str(container.name)[:str(container.name).find('_')]
#commands = []
#commands.append('ovs-vsctl add-br ' + bridge)
#commands.append('ifconfig ' + bridge + ' up')

#runPigRelay(container)
#runSSH(commands)
#startSnort(container)
#stopSnort(container)
#changeRules("kiran",container)
#runContainer(host_ip,'1234','tcp')
