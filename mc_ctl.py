import os
import sys
import urllib.request
import pathlib
import datetime

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
GITHUB_RAW_URL = 'https://raw.githubusercontent.com'
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
USAGE = '''
Usage: {0} [create|backup|destroy|destroy_without_backup|help] [target]
    create: Create and serve minecraft server
        {0} create [world_repository] [version|LATEST|SNAPSHOT]
        ex: {0} create hungcat/minecraft-world 1.14.4
    backup: Back up current world to corresponding github repository
        {0} backup [world_repository]
        ex: {0} backup hungcat/minecraft-world
    destroy: Destroy current world with backup
        {0} destroy [world_repository]
        ex: {0} destroy hungcat/minecraft-world
    destroy_without_backup: Destroy current world without backup
        {0} destroy_without_backup [world_repository]
        ex: {0} destroy_without_backup hungcat/minecraft-world
    restart: Restart minecraft server
        {0} restart [world_repository]
        ex: {0} restart hungcat/minecraft-world
    rcon: Run rcon-cli command
        {0} rcon [world_repository] [command]
        ex: {0} rcon hungcat/minecraft-world /help
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
        version = ''
        if argc > 1:
            action = args[1]
        if argc > 2:
            world_name = args[2]
        if argc > 3:
            version = args[3]

    try:
        if action == 'create':
            print(_emoji(':muscle: Creating server...(first creation takes a bit time for downloading image)'))
            print(create_server(world_name, version))
        elif action == 'list':
            print(_emoji(':muscle: Listing server...'))
            print(list_server())
        elif action == 'backup':
            print(_emoji(':muscle: Backuping world data...'))
            print(backup_world(world_name))
        elif action == 'destroy':
            print(_emoji(':muscle: Backuping world data...'))
            print(backup_world(world_name))
            print(_emoji(':muscle: Destroying server...'))
            print(destroy_server(world_name))
        elif action == 'destroy_without_backup':
            print(_emoji(':muscle: Destroying server...'))
            print(destroy_server(world_name))
        elif action == 'help':
            print(USAGE)
        elif action == 'restart':
            print(_emoji(':muscle: Restarting minecraft server...'))
            print(do_commands(world_name, [ 'docker restart minecraft' ]))
        elif action == 'rcon':
            print(_emoji(':muscle: Restarting minecraft server...'))
            print(do_commands(world_name, [ 'docker exec rcon-cli {}'.format(version) ]))
        else:
            print('Invalid action: {}'.format(action))
            print(USAGE)
    except Exception as e:
        print(_emoji(':no_good: Error: {}'.format(e)))

    return


def list_server():
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    return manager.get_all_droplets()

def create_server(world_name='', version=''):
    try:
        commands, version = _construct_droplet_docker_commands(world_name, version)
    except Exception as e:
        return _emoji(':no_good: Exit: {}'.format(e))

    private_key, public_key = _get_ssh_keys()
    droplet = _create_droplet(public_key, world_name)
    print('Droplet has created. Run minecraft...')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ip_address = _get_ip_address_of_droplet(droplet)
    _ssh_connect(client, hostname=ip_address, username='root', pkey=private_key)
    status = _exec_commands(client, commands, ignore_error=True)

    if status == 0:
        print('Minecraft has waked up!')
        message = _emoji(':hammer_and_pick: Created minecraft {} instance: `{}`'.format(version, ip_address))
    else:
        print('Minecraft couldn\'t wake up!')
        print(_emoji(':muscle: Destroying server...'))
        message = _emoji(':cry: Failed to create server...')
        try:
            destroy_server()
        except Exception as e:
            print(_emoji(':no_good: Error: {}'.format(e)))
            print(_emoji(':cry: Please destroy this server yourself...'))

    return message

def _construct_droplet_docker_commands(world_name, version):
    backup_url = _construct_github_url(world_name)
    version_url = _construct_github_url(world_name, path='master/MCCTL_VERSION.txt', is_raw=True)
    commands = [
        'apt install -y git'
    ]

    if _test_github_url(backup_url) == True:
        commands.append('git clone {} /root/data'.format(backup_url))

        v = ''
        try:
            with urllib.request.urlopen(urllib.request.Request(version_url)) as res:
                v = res.read().decode('utf-8')
        except urllib.request.URLError as e:
            print(_emoji(':information: MCCTL_VERSION.txt may not exists: {}'.format(e)))
        if v != '':
            if version == '':
                version = v
            else:
                if _yes_no_input('Last run version is {}. Run version {} now?'.format(v, version)) == False:
                    raise Exception('Disagreed with version setting')

    if version == '':
        version = 'LATEST'

    commands.append('docker run -d -v /root/data:/data -e EULA=TRUE -e VERSION={} -e WORLD=/data/world --name minecraft -p 25565:25565 --restart always itzg/minecraft-server'.format(version))

    return commands, version


def backup_world(world_name=''):
    backup_url = _construct_github_url(world_name)
    output_url = '{}/{}'.format(GITHUB_URL, world_name)
    if _test_github_url(backup_url) == False:
        return _emoji(':thinking_face: Unavailable repository: {}'.format(output_url))

    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    all_droplets = manager.get_all_droplets()
    target = filter(lambda droplet: droplet.name == 'minecraft-{}'.format(world_name), all_droplets)
    if len(target) == 0:
        target = filter(lambda droplet: droplet.name == 'minecraft-', all_droplets)
        if len(target) == 0:
            return _emoji(':thinking_face: That world is not running')
        elif _yes_no_input('Overwrite {} with running new minecraft world?'.format(output_url)) == False:
            return _emoji(':raised_hand: Cannceled overwriting {} with running new minecraft world'.format(output_url))
    droplet = target[0]

    private_key = _get_ssh_keys()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ip_address = _get_ip_address_of_droplet(droplet)
    _ssh_connect(client, hostname=ip_address, username='root', pkey=private_key)

    status = _exec_commands(client, [
        'cd /root/data',
        '[ -d .git ] || git init && git remote add origin {} && git config branch.master.remote origin && git config branch.master.merge refs/heads/master'.format(backup_url),
        r'find /root/data -maxdepth 1 -name *.jar -print0 -quit | sed -e "s,^.*/[^.]*\.\([0-9.]*\)\.jar\x0$,\1," > MCCTL_VERSION.txt'
        '[ -f .gitignore ] || echo "/minecraft_server*.jar" > .gitignore',
        'git add --all',
        'git commit -m "world `cat MCCTL_VERSION.txt` update [{}]"'.format(version, datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y/%m/%d %H:%M:%S%z')),
        'git push'
    ])

    if status == 0:
        message = _emoji(':rocket: Backuped world: {}'.format(output_url))
    else:
        message = _emoji(':cry: Failed to backup')

    return message

def destroy_server(world_name=''):
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    all_droplets = manager.get_all_droplets()
    target = filter(lambda droplet: droplet.name == 'minecraft-{}'.format(world_name), all_droplets)
    if len(target) == 0:
        message = _emoji(':thinking_face: That world is not running')
        return message
    droplet = target[0]

    ip_address = _get_ip_address_of_droplet(droplet)
    droplet.destroy()

    message = _emoji(':boom: Destroyed instance: `{}`'.format(ip_address))
    return message

def do_commands(world_name='', commands=[]):
    manager = digitalocean.Manager(token=DIGITALOCEAN_API_TOKEN)
    all_droplets = manager.get_all_droplets()
    target = filter(lambda droplet: droplet.name == 'minecraft-{}'.format(world_name), all_droplets)
    if len(target) == 0:
        return _emoji(':thinking_face: That world is not running')
    droplet = target[0]

    private_key = _get_ssh_keys()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ip_address = _get_ip_address_of_droplet(droplet)
    _ssh_connect(client, hostname=ip_address, username='root', pkey=private_key)

    status = _exec_commands(client, commands)

    if status == 0:
        message = _emoji(':thumbs_up: Commands succeeded!')
    else:
        message = _emoji(':cry: Commands failed...')

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


def _create_droplet(public_key, world_name=''):
    key_name = 'hungcat-mc-ctl-' + public_key[-7:]
    droplet_name = 'minecraft-{}'.format(world_name)
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

    key_file_dir = SCRIPT_DIR / 'keys'
    private_key_file_path = key_file_dir / key_file_name
    public_key_file_path = key_file_dir / '{}.pub'.format(key_file_name)

    try:
        private_key = RSA.import_key(private_key_file_path.read_bytes()).export_key()
        public_key = RSA.import_key(public_key_file_path.read_bytes()).publickey().export_key()
    except:
        private_key, public_key = _generate_ssh_key(key_file_name)

    return private_key, public_key

def _generate_ssh_key(key_file_name):
    key = RSA.generate(4096)
    private_key = key.exportKey()
    public_key = key.publickey().exportKey()

    key_file_dir = SCRIPT_DIR / 'keys'
    private_key_file_path = key_file_dir / key_file_name
    public_key_file_path = key_file_dir / '{}.pub'.format(key_file_name)

    key_file_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_key_file_path.write_bytes(private_key)
    private_key_file_path.chmod(0o600)
    public_key_file_path.write_bytes(public_key)
    public_key_file_path.chmod(0o600)

    return private_key, public_key

def _construct_github_url(world_name, path='', is_raw=False):
    if is_raw:
        url = furl(GITHUB_RAW_URL)
    else:
        url = furl(GITHUB_URL)
    #parsed.scheme = 'https'
    url.path = '{}/{}'.format(url.path, world_name)
    if path != '':
        url.path = '{}/{}'.format(url.path, path)
    url.username = GITHUB_USER
    url.password = GITHUB_TOKEN
    return url.tostr()

def _test_github_url(github_url):
    try:
        git.cmd.Git().ls_remote(github_url)
    except git.GitCommandError as e:
        return False
    return True

def _yes_no_input(message):
    while True:
        choice = input("{} [y[es]/n[o]]: ".format(message)).lower()
        if choice in ['y', 'ye', 'yes']:
            return True
        elif choice in ['n', 'no']:
            return False

def _emoji(mes):
    return emoji.emojize(mes, use_aliases=True)

if __name__ == '__main__':
    command_handler(sys.argv)

