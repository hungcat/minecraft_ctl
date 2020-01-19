import os
import sys

# furl
from furl import furl
# GitPython
import git
# python-digitalocean
import digitalocean
# paramiko
import paramiko
# cryptodomex
from Cryptodome.PublicKey import RSA
# retry
from retry import retry
# emoji
import emoji

DIGITALOCEAN_API_TOKEN = os.getenv('DIGITALOCEAN_API_TOKEN')
DIGITALOCEAN_REGION_SLUG = os.getenv('DIGITALOCEAN_REGION_SLUG')
GITHUB_USER = os.getenv('GITHUB_USER')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

GITHUB_URL = 'https://github.com'
SCRIPT_DIR = os.path.dirname(__file__)
USAGE = '''
Usage: {0} [create|backup|destroy|destroy_without_backup|help] [target]
    create: Create and serve minecraft server
        {0} create [world_repository] [version|LATEST|SNAPSHOT]
        ex: {0} create hungcat/minecraft_world 1.14.4
    backup: Back up current world to corresponding github repository
        {0} backup [world_repository]
        ex: {0} backup hungcat/minecraft_world
    destroy: Destroy current world with backup
        {0} destroy [world_repository]
        ex: {0} destroy hungcat/minecraft_world
    destroy_without_backup: Destroy current world without backup
        {0} destroy_without_backup [world_repository]
        ex: {0} destroy_without_backup hungcat/minecraft_world
    list: List running worlds
        {0} list
    help: Show this
        {0} help

Required environment variables:
    DIGITALOCEAN_API_TOKEN (mandantory)
        API token of digitalocean.
    DIGITALOCEAN_REGION_SLUG (optional)
        Region slug of digitalocean droplet.
        The closest one to Japan is sgp1(Singapore)
    GITHUB_USER (for backup)
        User ID of github for backup the world.
    GITHUB_TOKEN (for backup)
        Personal access token of github for backup the world.
        ref: https://help.github.com/ja/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line
'''.format(__file__).strip()


def command_handler(args):
    argc = len(args)
    if argc < 2:
        # show usage
        print(USAGE)
        return
    else:
        world_name = ''
        version = 'LATEST'
        if argc > 1:
            action = args[1]
        if argc > 2:
            world_name = args[2]
        if argc > 3:
            version = args[3]

    try:
        if action == 'create':
            print(emoji.emojize(':muscle: Creating server...', use_aliases=True))
            print(create_server(world_name, version))
        elif action == 'list':
            print(emoji.emojize(':muscle: Listing server...', use_aliases=True))
            print(list_server())
        elif action == 'backup':
            print(emoji.emojize(':muscle: Backuping world data...', use_aliases=True))
            print(backup_world(world_name))
        elif action == 'destroy':
            print(emoji.emojize(':muscle: Backuping world data...', use_aliases=True))
            print(backup_world(world_name))
            print(emoji.emojize(':muscle: Destroying server...', use_aliases=True))
            print(destroy_server(world_name))
        elif action == 'destroy_without_backup':
            print(emoji.emojize(':muscle: Destroying server...', use_aliases=True))
            print(destroy_server(world_name))
        elif action == 'help':
            print(USAGE)
        else:
            print('Invalid action: {}'.format(action))
            print(USAGE)
    except Exception as e:
        print(emoji.emojize(':no_good: Error: {}'.format(e), use_aliases=True))

    return


def list_server():
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    return manager.get_all_droplets()

def create_server(world_name='', version='LATEST'):
    backup_url = _construct_github_url(world_name)

    private_key, public_key = _get_ssh_keys()
    droplet = _create_droplet(public_key, world_name)
    print('Droplet has created. Run minecraft...')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ip_address = _get_ip_address_of_droplet(droplet)
    _ssh_connect(client, hostname=ip_address, username='root', pkey=private_key)

    commands = [
        'apt install -y git',
        'mkdir -p /root/backup',
        'git clone {} /root/backup/world'.format(backup_url),
        'docker run -d -v /root/backup:/data -e EULA=TRUE -e VERSION={} -e WORLD=/data/world --name minecraft -p 25565:25565 itzg/minecraft-server'.format(version)
    ]
    if _test_github_url(backup_url) == False:
        commands.pop(2)

    status = _exec_commands(client, , ignore_error=True)
    if status == 0:
        print('Minecraft has waked up!')
        message = emoji.emojize(':hammer_and_pick: Created instance: `{}`'.format(ip_address), use_aliases=True)
    else:
        print('Minecraft couldn\' wake up!')
        print(emoji.emojize(':muscle: Destroying server...', use_aliases=True))
        message = emoji.emojize(':cry: Failed to create server...', use_aliases=True)
        try:
            destroy_server()
        except Exception as e:
            print(emoji.emojize(':no_good: Error: {}'.format(e), use_aliases=True))
            print(emoji.emojize(':cry: Please destroy this server yourself...', use_aliases=True))

    return message

def backup_world(world_name='default'):
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    all_droplets = manager.get_all_droplets()
    target = filter(lambda droplet: droplet.name == 'minecraft_{}'.format(world_name), all_droplets)
    if len(target) == 0:
        message = emoji.emojize(':thinking_face: That world is not running', use_aliases=True)
        return message
    droplet = target[0]

    private_key = _get_ssh_keys()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ip_address = _get_ip_address_of_droplet(droplet)
    _ssh_connect(client, hostname=ip_address, username='root', pkey=private_key)

    _exec_commands(client, [
        'cd /root/backup/world',
        '[ -d .git ] || git init && git remote add origin {} && git config branch.master.remote origin && git config branch.master.merge refs/heads/master'.format(_construct_github_url(world_name)),
        'git add --all',
        'git commit -m "world update"',
        'git push'
    ])

    message = emoji.emojize(':rocket: Backuped world: {}/{}'.format(GITHUB_URL, world_name), use_aliases=True)
    return message

def destroy_server(world_name='default'):
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    all_droplets = manager.get_all_droplets()
    target = filter(lambda droplet: droplet.name == 'minecraft_{}'.format(world_name), all_droplets)
    if len(target) == 0:
        message = emoji.emojize(':thinking_face: That world is not running', use_aliases=True)
        return message
    droplet = target[0]

    ip_address = _get_ip_address_of_droplet(droplet)
    droplet.destroy()

    message = emoji.emojize(':boom: Destroyed instance: `{}`'.format(ip_address), use_aliases=True)
    return message

@retry(tries=30, delay=5)
def _ssh_connect(client, hostname, username, pkey):
    print('Trying SSH connection... IP: {}'.format(hostname)) 
    client.connect(hostname=hostname, username=username, pkey=pkey)

def _exec_commands(client, commands, ignore_error=False):
    for command in commands:
        print('[[Executing {}]]'.format(command)) 
        chan = client.get_transport().open_session()
        chan.set_combine_stderr(True)
        chan.exec_command(command + ' ; exit "$?"')
        stdouterr = chan.makefile('rb', -1)
        status = chan.recv_exit_status()
        print(stdouterr.read().decode('utf-8'))

        if ignore_error == False and status != 0:
            print('[[Stop since some error occured]] status: {}'.format(status))
            return status
    return 0


def _create_droplet(public_key, world_name='default'):
    key_name = 'hungcat-mc-ctl-' + public_key[-7:]
    droplet_name = 'minecraft_{}'.format(world_name)
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)

    all_droplets = manager.get_all_droplets()
    existing_droplets = filter(lambda droplet: droplet.name == droplet_name, all_droplets)

    minecraft_droplet = None

    if len(existing_droplets) == 0:
        keys = manager.get_all_sshkeys()
        if len(filter(lambda k: k.name == key_name, keys)) == 0:
            key = digitalocean.SSHKey(token=DIGITALOCEAN_API_TOKEN,
                                    name=key_name,
                                    public_key=public_key)
            key.create()
            keys.append(key)
        droplet = digitalocean.Droplet(token=DIGITALOCEAN_API_TOKEN,
                                    name=droplet_name,
                                    region= DIGITALOCEAN_REGION_SLUG if DIGITALOCEAN_REGION_SLUG is not None else 'sgp1',
                                    image='docker-18-04',
                                    size_slug='2gb',
                                    ssh_keys=keys,
                                    backups=False)
        droplet.create()
        minecraft_droplet = manager.get_droplet(droplet.id)
    else:
        minecraft_droplet = existing_droplets[0]

    return minecraft_droplet

@retry(tries=10, delay=3)
def _get_ip_address_of_droplet(droplet):
    droplet.load()
    if droplet.ip_address is None:
        raise Exception('Failed to obtain IP address')
    return droplet.ip_address

def _get_ssh_keys():
    key_file_name = 'id_rsa'

    key_file_dir = '{}/keys'.format(SCRIPT_DIR)
    private_key_file_path = '{}/{}'.format(key_file_dir, key_file_name)
    public_key_file_path = '{}/{}.pub'.format(key_file_dir, key_file_name)

    try:
        with open('{}/{}'.format(private_key_file_path, key_file_name), 'rb') as content_file:
            private_key = RSA.import_key(content_file.read()).export_key()
        with open('{}/{}'.format(public_key_file_path, key_file_name), 'rb') as content_file:
            public_key = RSA.import_key(content_file.read()).publickey().export_key()
    except:
        private_key, public_key = _generate_ssh_key(key_file_name)

    return private_key, public_key

def _generate_ssh_key(key_file_name):
    key = RSA.generate(4096)
    skey = key.exportKey()
    pkey = key.publickey().exportKey()

    key_file_dir = '{}/keys'.format(SCRIPT_DIR)
    private_key_file_path = '{}/{}'.format(key_file_dir, key_file_name)
    public_key_file_path = '{}/{}.pub'.format(key_file_dir, key_file_name)


    if not os.path.isdir(key_file_dir):
        os.makedirs(key_file_dir)
        os.chmod(key_file_dir, 0o700)
    with open(private_key_file_path, 'wb') as content_file:
        os.chmod(private_key_file_path, 0o600)
        content_file.write(private_key)
    with open(public_key_file_path, 'wb') as content_file:
        os.chmod(public_key_file_path, 0o600)
        content_file.write(public_key)

    return private_key, public_key

def _construct_github_url(world_name):
    url = furl(GITHUB_URL)
    #parsed.scheme = 'https'
    url.path = '{}/{}'.format(url.path, world_name)
    url.username = GITHUB_USER
    url.password = GITHUB_TOKEN
    return url.tostr()

def _test_github_url(github_url):
    try:
        git.cmd.Git().ls_remote(github_url)
    except git.GitCommandError as e:
        return False
    return True

if __name__ == '__main__':
    command_handler(sys.argv)