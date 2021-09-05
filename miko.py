#! /usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import urllib.request
import time  # used to insert pauses in the script
import telnetlib
import sys
import os
import json
from getpass import getpass
import subprocess
import pip

if not os.path.isdir("./lib/git"):
   pip.main(['install', 'GitPython', '-t', './lib/git'])
sys.path.append("./lib/git")
import git

if not os.path.isdir("./lib/netmiko"):
   pip.main(['install', 'netmiko', '-t', './lib/netmiko'])
sys.path.append("./lib/netmiko")
from netmiko import ConnectHandler
from netmiko.base_connection import BaseConnection


def sshKeyGen(arg=""):
   while True:
      yesno = ""
      if arg == "":
         path = './.ssh/id_rsa'
         yesno = input("\nGithub接続用ssh keyの準備はお済みですか？(y/n): ")
      else:
         path = arg
      if yesno == "y":
         ssh_privkey_path = input("ssh privkey path: ")
         break
      elif yesno == "n" or not arg == "":
         print("接続用のssh keyを作成します。")
         if not os.path.isdir('./.ssh'):
            subprocess.call(['mkdir', './.ssh'])
         subprocess.call(['ssh-keygen', '-t', 'rsa', '-b', '4096', '-q', '-f', path, '-N', ''])
         print()
         subprocess.call(['cat', './.ssh/id_rsa.pub'])
         print("\n鍵ファイル(" + path + " " + path + ".pub)を生成しました。表示されている公開鍵をGithubに登録してください。")
         input("登録が完了したら[ENTER]を押してください: ")
         ssh_privkey_path = path
         break
      print("oops")
   return os.path.abspath(ssh_privkey_path)


# configファイル存在確認 なければ作成
def initialization():
   if not os.path.isfile("config.json"):
      # パラメータ入力
      print("設定ファイルが見つからなかったので、初期設定を実施します。\n")
      zab_url = input("Zabbix API URL: ")
      zab_key = input("Zabbix API KEY: ")
      device_user = input("Device login user: ")
      device_pass = getpass(prompt="Device login password (hidden): ")
      device_enable = getpass(prompt="Device enable password (hidden): ")
      nw_config_file_path = input("Config save to (dir): ")
      github_email = input("Github E-mail address: ")
      github_name = input("Github username: ")
      ssh_privkey_path = sshKeyGen()
      # JSON生成・ファイル書き込み
      config_json = {'zab_url': zab_url, 'zab_key': zab_key, 'device_user': device_user, 'device_pass': device_pass,
                     'device_enable': device_enable, 'nw_config_file_path': nw_config_file_path,
                     'github_email': github_email, 'github_name': github_name, 'ssh_privkey_path': ssh_privkey_path}
      with open('config.json', 'w') as f:
         json.dump(config_json, f, indent=3, ensure_ascii=False)
      print("設定ファイル「config.json」を作成しました。設定を変更する場合はこのファイルを直接編集するか、ファイルを削除して再度初期設定を実施してください。\n")


class miko:
   zab_url = ""
   zab_key = ""
   device_user = ""
   device_pass = ""
   device_enable = ""
   nw_config_file_path = ""
   repo = ""
   ssh_privkey_path = ""

   def __init__(self):
      initialization()
      # configファイル読み込み
      with open('config.json') as f:
         config_json = json.load(f)
      self.zab_url = config_json['zab_url']
      self.zab_key = config_json['zab_key']
      self.device_user = config_json['device_user']
      self.device_pass = config_json['device_pass']
      self.device_enable = config_json['device_enable']
      self.nw_config_file_path = config_json['nw_config_file_path']
      self.github_email = config_json['github_email']
      self.github_name = config_json['github_name']
      self.ssh_privkey_path = config_json['ssh_privkey_path']

      # gitからclone
      self.gitClone()
      os.chdir(self.nw_config_file_path)
      self.repo = git.Repo()
      os.chdir('../')

      # debug
      # print(self.zab_url)
      # print(self.zab_key)
      # print(self.device_user)
      # print(self.device_pass)
      # print(self.device_enable)
      # print(self.nw_config_file_path)
      # exit()

   # git リポジトリclone
   def gitClone(self):
      if not os.path.isdir(self.nw_config_file_path):
         print("configで指定されたリポジトリがないため、gitからcloneします。もしくは^Cで中断して正しいディレクトリ名をconfig.jsonに書き込んでください。")
         git_url = input("Git URL(SSH): ")

         if not os.path.isfile(self.ssh_privkey_path):
            sshKeyGen(self.ssh_privkey_path)

         # gitpythonで鍵ファイルを指定してcloneする方法がわからなかったので、泣く泣くunixコマンドで対応
         # repo = git.Git().clone(git_url, self.nw_config_file_path)
         sshcommand = 'core.sshCommand=\"/usr/bin/ssh -i ' + self.ssh_privkey_path + '\"'  # + ' -F /dev/null"'
         res = subprocess.run('git -c ' + sshcommand + ' clone ' + git_url + " " + self.nw_config_file_path, shell=True,
                              stdout=subprocess.PIPE)
         print(res)
         os.chdir(self.nw_config_file_path)
         repo = git.Repo()
         os.chdir('../')

         repo.git.config('user.email', self.github_email)
         repo.git.config('user.name', self.github_name)
         repo.git.config('core.sshCommand', 'ssh -F /dev/null -i ' + self.ssh_privkey_path)

   # Zabbixから機器のInventory情報取得
   def getInventoryFromZab(self, hostname=""):
      zabjson = {
         "jsonrpc": "2.0",
         "method": "host.get",
         "params": {
            "output": [
               "host"
            ],
            "filter": {
               "host": hostname
            },
            "selectInventory": [
               "os"
            ],
            "searchInventory": {
               "type": "NW"
            }
         },
         "id": 2,
         "auth": self.zab_key
      }

      httpheaders = {
         'Content-Type': 'application/json-rpc',
      }

      req = urllib.request.Request(self.zab_url, json.dumps(zabjson).encode(), httpheaders)
      with urllib.request.urlopen(req) as res:
         body = res.read()
         return body.decode()

   # 機器からconfig取得 ファイルにtextで保存
   def getConfigFromDivice(self, host):
      # a list of the hosts we wish to access
      global output
      device = {
         'ip': host["hostname"],
         'device_type': host["device_type"],
         'username': self.device_user,
         'password': self.device_pass,
         'port': 22,  # optional, defaults to 22
         'secret': self.device_enable,  # optional, defaults to ''
         'verbose': False,  # optional, defaults to False
      }

      # Create a new Paramiko SSH connection object

      # Issue commands
      if host["device_type"] in {"juniper"}:  # juniper
         net_connect = ConnectHandler(**device)
         output = net_connect.send_command('show config')
         output += net_connect.send_command('show config | display set')
      elif host["device_type"] in {"cisco_ios"}:  # cisco-ios
         net_connect = ConnectHandler(**device)
         net_connect.enable()
         output = net_connect.send_command('show running-config')
         output += net_connect.send_command(
            'show archive config differences nvram:startup-config system:running-config')
      elif host["device_type"] in {"nec-ix"}:  # nec-ix(対応していないので即return)
         output = "skip"
         return

         # tn = telnetlib.Telnet(host["hostname"], 23)
         # time.sleep(3)
         # tn.read_until(b"login: ", 2)
         # print(device["username"])
         # time.sleep(3)
         # tn.write(device["username"].encode('ascii') + b"\n")
         # time.sleep(3)
         # tn.read_until(b"Password: ", 2)
         # print(device["password"])
         # time.sleep(3)
         # tn.write(device["password"].encode('ascii') + b"\n")
         # tn.read_until(b"# ", 2)
         # tn.write(b"enable-config" + b'\r')
         # tn.read_until(b"(config)# ", 2)
         # tn.write(b"terminal length 0" + b'\r')
         # tn.read_until(b"(config)# ", 2)
         # tn.write(b"running-config" + b'\r')
         # output = tn.read_until(b"(config)# ").decode('ascii')
         # tn.write(b"exit" + b'\r')
         # tn.close()
      elif host["device_type"] in {"generic"}:  # 一般(個別に対応しているものがあれば適宜追加)
         net_connect = ConnectHandler(**device)
         net_connect.enable()
         output = net_connect.send_command('show running-config')

      f = open(self.nw_config_file_path + host["hostname"], 'w', encoding='UTF-8')
      print(output)
      f.write(output)
      f.close

   # git diff確認
   def checkGitDiff(self, hostname):
      diff = self.repo.git.diff(hostname)
      if diff == "":
         return False
      else:
         print(diff)
         return True

   # config取得前に実行すること configファイルにdiffがあったらgitから強制pull
   def gitPullForce(self):
      os.chdir(self.nw_config_file_path)
      if self.checkGitDiff('*'):
         self.repo.git.fetch('origin', 'main')
         self.repo.git.reset('--hard', 'origin/master')
         print("*** the repository is reset ***")
      else:
         print("No diff")
      os.chdir('../')

   # configファイルをgitにpush
   def pushConfigToGithub(self, hostname):
      print(hostname)
      print(self.nw_config_file_path)
      if not os.path.isfile(self.nw_config_file_path + hostname):
         return
      os.chdir(self.nw_config_file_path)
      if self.checkGitDiff(hostname):
         self.repo.git.add(hostname)
         self.repo.git.commit(hostname, '-m', hostname + ' from miko')
         self.repo.remotes.origin.push()
         # origin = self.repo.remote(name='origin')
         # origin.push()
      else:
         print("No diff")
      os.chdir('../')


if __name__ == '__main__':
   # コマンドライン引数から先頭のファイル名を除去し、ホスト名のみの配列を生成
   sys.argv.pop(0)
   hostname = sys.argv
   # ex) hostname = ["srx300","841m"]

   m = miko()
   # zabbixからインベントリを取得
   zabbixjson = m.getInventoryFromZab(hostname)
   zabbixdata = json.loads(zabbixjson)
   print(zabbixjson)

   # zabbixインベントリから機器config取得に必要な情報を抜き出す hostごとに配列に整形
   results = zabbixdata["result"]
   hosts = []
   for result in results:
      print(result["host"])
      print(result["inventory"]["os"])
      hosts.append({"hostname": result["host"], "device_type": result["inventory"]["os"]})

   # 上記配列から1つずつ、機器にログインしてconfigを取得して保存 gitにpush
   m.gitPullForce()
   for host in hosts:
      m.getConfigFromDivice(host)
      m.pushConfigToGithub(host['hostname'])

   print("###end###")
   exit()
