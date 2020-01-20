# minecraft_ctl
Python script to manage minecraft server on docker on digitalocean droplet

# Usage
```
 git clone https://github.com/hungcat/minecraft_ctl
 cd minecraft_ctl
 pip3 install -r requirements.txt
 python3 mc_ctl.py help
```

```
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
```
ref: https://help.github.com/ja/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line
+ Info about github access token

ref: https://github.com/morishin/minecraft-lambda-function

ref: https://github.com/itzg/docker-minecraft-server
