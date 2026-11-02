#! /usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import time  # used to insert pauses in the script
import sys
import os
from getpass import getpass
import subprocess
import socket
import argparse

import git

from netmiko import ConnectHandler
from netmiko.base_connection import BaseConnection
from netmiko.ssh_autodetect import SSHDetect

def parse_args():
   """引数をパース"""
   parser = argparse.ArgumentParser(
      description="netmikoでNW機器からConfigを取得します。\nホスト名は後ろに\"/\"を続けてIPアドレスを直接指定できます。",
      epilog="例: \n%(prog)s -n device/192.0.2.1\n%(prog)s -f file.txt (ファイルで指定)",
   )

   parser.add_argument(
      "-f", "--file",
      action='append',
      # default="",
      help="収集対象ホストをファイルから指定する",
   )

   parser.add_argument(
      "-n", "--hostname",
      action='append',
      # default="",
      help="収集対象ホストをホスト名で指定する",
   )

   # 真偽値フラグ (store_true)
   parser.add_argument(
      "-r", "--resolve_only",
      action="store_true",
      help="ホスト名とIPアドレスの関係のみ出力し、Config収集・Pushは行わない",
   )

   # 真偽値フラグ (store_true)
   parser.add_argument(
      "-g", "--get_only",
      action="store_true",
      help="ホスト名とIPアドレスの関係の出力とConfig収集のみ行い、・Pushは行わない",
   )

   return parser.parse_args()


def DNSResolve(hostname):
   """ホスト名に対応するIPアドレス(IPv4/IPv6)を重複なく順序を保って返す。"""
   try:
      infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
   except socket.gaierror as e:
      print(f"{hostname}\t名前解決に失敗しました: {e}", file=sys.stderr)
      sys.exit(exit_code)

   addrs = []
   for family, _, _, _, sockaddr in infos:
      addr = sockaddr[0]
      if addr not in addrs:
         addrs.append(addr)
      print(f"* {hostname}\t{addr}")
   print(f"=> {addrs[0]}")
   return addrs[0]

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
      device_user = input("Device login user: ")
      device_pass = getpass(prompt="Device login password (hidden): ")
      device_enable = getpass(prompt="Device enable password (hidden): ")
      nw_config_file_path = input("Config save to (dir): ")
      github_email = input("Github E-mail address: ")
      github_name = input("Github username: ")
      ssh_privkey_path = sshKeyGen()
      # JSON生成・ファイル書き込み
      config_json = {'device_user': device_user, 'device_pass': device_pass,
                     'device_enable': device_enable, 'nw_config_file_path': nw_config_file_path,
                     'github_email': github_email, 'github_name': github_name, 'ssh_privkey_path': ssh_privkey_path}
      with open('config.json', 'w') as f:
         json.dump(config_json, f, indent=3, ensure_ascii=False)
      print("設定ファイル「config.json」を作成しました。設定を変更する場合はこのファイルを直接編集するか、ファイルを削除して再度初期設定を実施してください。\n")


class miko:
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
      # print(self.device_user)
      # print(self.device_pass)
      # print(self.device_enable)
      # print(self.nw_config_file_path)
      # exit()

   # git リポジトリclone
   def gitClone(self):
      if not os.path.isdir(self.nw_config_file_path):
         print("configで指定されたリポジトリがないため、gitからcloneします。もしくは^Cで中断してconfig.jsonに正しいディレクトリ名を書き込んでください。")
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

   # config取得前に実行すること configファイルにdiffがあったらgitから強制pull
   def gitPullForce(self):
      os.chdir(self.nw_config_file_path)
      if self.checkGitDiff('*'):
         self.repo.git.fetch('origin', 'main')
         self.repo.git.reset('--hard', 'origin/main')
         print("*** the repository is reset ***")
      else:
         print("No need Git pull")
      os.chdir('../')

   # git diff確認
   def checkGitDiff(self, hostname):
      diff = self.repo.git.diff("--ignore-all-space", hostname) # 空白行を無視
      if diff == "":
         print("No git diff")
         return False
      else:
         print(diff)
         time.sleep(1)
         return True

   # configファイルをgitにpush
   def pushConfigToGithub(self, hostname):
      # print(self.nw_config_file_path)
      print("Git push")
      time.sleep(1)
      if not os.path.isfile(self.nw_config_file_path + hostname):
         return
      os.chdir(self.nw_config_file_path)
      self.repo.git.add(hostname, "--intent-to-add") # 新規ファイルをdiffに追加
      if self.checkGitDiff(hostname):
         output = self.repo.git.add(hostname)
         print(output)
         output = self.repo.git.commit(hostname, '-m', hostname + ' from miko')
         print(output)
         output = self.repo.remotes.origin.push()
         print(output)
         # origin = self.repo.remote(name='origin')
         # origin.push()
      else:
         print("No git push")
      os.chdir('../')

   def detectDeviceType(self, host):
      # a list of the hosts we wish to access
      output = ""
      device = {
         'ip': host["address"],
         # 'ip': host["hostname"],
         'device_type': "autodetect",
         # 'device_type': host["device_type"],
         'username': self.device_user,
         'password': self.device_pass,
         'port': 22,  # optional, defaults to 22
         'secret': self.device_enable,  # optional, defaults to ''
         'verbose': False,  # optional, defaults to False
         #'ssh_config_file': "~/.ssh/config",
         'disabled_algorithms': {"Kex":["diffie-hellman-group14-sha1"], "HostKey":["ssh-rsa"]},
      }

      # detect device_type
      print(f"detect device-type...")
      net_connect = SSHDetect(**device)
      device_type = net_connect.autodetect()
      print(f"type: {device_type}")
      time.sleep(2)
      return device_type


   # 機器からconfig取得 ファイルにtextで保存
   def getConfigFromDivice(self, host, push=True):
      # a list of the hosts we wish to access
      output = ""
      print(host["address"])
      device = {
         'ip': host["address"],
         'device_type': host["device_type"],
         'username': self.device_user,
         'password': self.device_pass,
         'port': 22,  # optional, defaults to 22
         'secret': self.device_enable,  # optional, defaults to ''
         'verbose': False,  # optional, defaults to False
         #'ssh_config_file': "~/.ssh/config",
         'disabled_algorithms': {"Kex":["diffie-hellman-group14-sha1"], "HostKey":["ssh-rsa"]},
      }

      # Create a new Paramiko SSH connection object
      # Issue commands
      if device["device_type"] in {"juniper_junos"}:  # juniper
         print(f"juniper_junos")
         net_connect = ConnectHandler(**device)
         output = net_connect.send_command('show config')
         output += net_connect.send_command('show config | display set')
      elif device["device_type"] in {"cisco_ios"}:  # cisco-ios
         print(f"cisco_ios")
         net_connect = ConnectHandler(**device)
         net_connect.enable()
         output = net_connect.send_command('show running-config')
         output += net_connect.send_command(
            'show archive config differences nvram:startup-config system:running-config')
      elif device["device_type"] in {"nec_ix"}:  # nec-ix
         print(f"nec_ix")
         # output = "skip"
         # return
         net_connect = ConnectHandler(**device)
         net_connect.enable()
         output = net_connect.send_command('show running-config')
      elif device["device_type"] in {"fortinet"}:  # fortinet
         print(f"fortinet")
         net_connect = ConnectHandler(**device)
         output = net_connect.send_command('show')
      elif device["device_type"] in {"generic"}:  # 一般(個別に対応しているものがあれば適宜追加)
         print(f"generic")
         net_connect = ConnectHandler(**device)
         net_connect.enable()
         output = net_connect.send_command('show running-config')
      else:
         print(f"no match device type: {device_type}")
         return

      print(output)
      time.sleep(3)
      if push:
         with open(self.nw_config_file_path + host["hostname"], 'w', encoding='UTF-8') as f:
            f.write(output)
      print("-----")

def main():
   args = parse_args()

   host_list = []
   if args.file == None and args.hostname == None:
      print(f"引数が足りません。 -hで詳細確認", file=sys.stderr)
   else:
      if not args.file == None:
         """ファイルから読み取り"""
         for file in args.file:
            try:
               with open(file) as f:
                  for str in f:
                     host = str.rstrip().split(' ')[0] # スペースより後ろは無視
                     """#で始まる行はコメントアウトで無視"""
                     if len(host) <= 0 or host[0] == "#":
                        continue
                     else:
                        host_list.append(host)
            except FileNotFoundError as e:
               print(f"ファイルがありません", file=sys.stderr)
      if not args.hostname == None:
         host_list.extend(args.hostname)



   hosts = []
   print(host_list)
   for host in host_list:
      host_split = host.split('/')
      if len(host_split) >= 2:
         print(f"{host_split[0]}: Use direct IPaddress mode.")
         hosts.append({"hostname": host_split[0], "address": host_split[1], "device_type": ""})
         print()
      else:
         print(f"{host_split[0]}: Use DNS mode.")
         hosts.append({"hostname": host_split[0], "address": DNSResolve(host_split[0]), "device_type": ""})
         print()

   if args.resolve_only:
      return

   m = miko()
   if args.get_only:
      """上記配列から1つずつ、機器にログインしてconfigを取得 保存はしない"""
      for host in hosts:
         print(host['hostname'])
         host["device_type"] = m.detectDeviceType(host)
         m.getConfigFromDivice(host, False)
         print()
   else:
      """上記配列から1つずつ、機器にログインしてconfigを取得して保存 gitにpush"""
      m.gitPullForce()
      for host in hosts:
         print(host['hostname'])
         host["device_type"] = m.detectDeviceType(host)
         m.getConfigFromDivice(host)
         m.pushConfigToGithub(host['hostname'])
         print()

   print("finish")
   exit()


if __name__ == '__main__':
   main()
