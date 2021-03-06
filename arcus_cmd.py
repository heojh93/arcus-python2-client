#!/usr/local/bin/python3

#
# arcus-python-client - Arcus python client drvier
# Copyright 2014 NAVER Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
 

from __future__ import division
from __future__ import absolute_import
import sys,os,socket,re

from optparse import OptionParser
from collections import OrderedDict

import paramiko

from arcus_util import zookeeper
from arcus_util import arcus_node

from kazoo.client import KazooClient
import kazoo
from io import open


# set below environment for dump_script
HOME_DIR=''
USER=''



def do_ssh_command(addr, command):
	ssh = paramiko.SSHClient()
	ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
	ssh.connect(addr)

	stdin, stdout, stderr = ssh.exec_command(command)
	for line in stdout.readlines():
		sys.stdout.write(line)
	ssh.close()


if __name__ == '__main__':
	usage = "usage: %prog [options]"
	parser = OptionParser(usage=usage, version="%prog 1.0")
	parser.add_option('-f', '--file', dest='file', default='', help='zookeeper address lists file')
	parser.add_option('-a', '--address', dest='address', default='', help='zookeeper address')
	parser.add_option('-s', '--service', dest='service', default='', help='service code')
	parser.add_option('-c', '--command', dest='command', default='', help='arcus command')
	parser.add_option('-n', '--node', dest='node', default='', help='node address or ip')
	parser.add_option('-x', '--ssh_command', dest='ssh_command', default='', help='ssh command execution')
	parser.add_option('', '--ssh_command_file', dest='ssh_command_file', default='', help='ssh command execution from file')
	parser.add_option('-i', '--i', dest='info', default=False, help='memory, maxconns info', action='store_true')
	parser.add_option('', '--dump_script', dest='dump_script', default=False, help='dump start script', action='store_true')
	parser.add_option('', '--vpn_remap', dest='vpn_remap', default='', help='read ip remap file for vpn network')
	parser.add_option('', '--all_node', dest='all_node', default=False, help='select all node', action='store_true')
	parser.add_option('', '--all_server', dest='all_server', default=False, help='select all server', action='store_true')
	parser.add_option('-t', '--timeout', dest='timeout', default='200', help='arcus command timeout (msec)')
	parser.add_option('-p', '--prefix_stats', dest='prefix', help='show arcus prefix stats')

	(options, args) = parser.parse_args()

	timeout = int(options.timeout) / 1000

	if options.file:
		fh = open(options.file)
		addresses = fh.readlines()
	else:
		addresses = [options.address]

	remap = {}
	if options.vpn_remap:
		fh = open(options.vpn_remap)
		lines = fh.readlines()
		for line in lines:
			if line.strip() == '' or line[0] == '#':
				continue
		
			fr, to = line.split()
			remap[fr] = to

	lists = [] # nodes
	zoo_caches = [] # caches (for cloud brief report)

	for address in addresses:
		if address.strip() == '' or address[0] == '#':
			continue
		

		try:
			if len(remap) > 0:
				addr, port = address.split(':')
				ip = socket.gethostbyname(addr)
				if ip in remap:
					print '## zookeeper ip remap %s -> %s for address %s' % (ip, remap[ip], addr)
					address = '%s:%s' % (remap[ip], port)
				
			#print(address)
			zoo = zookeeper(address)

			list = []
			if options.service:
				list = zoo.get_arcus_node_of_code(options.service, options.node)
				if len(list) > 0:
					print '\n\n## Zookeeper address %s' % address
			elif options.node:
				list = zoo.get_arcus_node_of_server(options.node)
				if len(list) > 0:
					print '\n\n## Zookeeper address %s' % address
			elif options.all_node:
				cache_list = zoo.get_arcus_cache_list()
				for cache in cache_list:
					list += zoo.get_arcus_node_of_code(cache, options.node)
			elif options.all_server:
				cache_list = zoo.get_arcus_cache_list()
				ip_map = {}
				for cache in cache_list:
					tmp = zoo.get_arcus_node_of_code(cache, options.node)
					for t in tmp:
						ip_map[t.ip] = True
						
				for k in ip_map:
					list.append(arcus_node(k, '*'))
				
			else:
				print '\n\n## Zookeeper address %s' % address
				cache = zoo.get_arcus_cache_list()
				print cache
				zoo_caches.append((zoo, cache))

			if options.dump_script: # record zookeeper address
				for node in list:
					node.zk_addr = address
				

		except kazoo.exceptions.NoNodeError:
			# not found
			continue

		lists = lists + list


	lists.sort(key = lambda x: x.ip + ":" + x.port)
	for node in lists:
		if node.ip in remap:
			print '## vpn remap %s -> %s' % (node.ip, remap[node.ip])
			node.ip = remap[node.ip]
			
		print node

	if options.ssh_command_file:
		fh = open(options.ssh_command_file)
		options.ssh_command = fh.read()

	if options.ssh_command:
		prev_ip = ''
		for node in lists:
			if prev_ip != node.ip: # run once per machine
				print '## run ssh command, [%s] %s' % (node.ip, options.ssh_command)
				do_ssh_command(node.ip, options.ssh_command)
				prev_ip = node.ip

	if options.command:
		for node in lists:

			try:
				result = node.do_arcus_command(options.command, timeout)
				print '%s\t\t%s - %s' % (node, options.command, result)
			except Exception, e:
				print '%s\t\tFAILED!!' % (node)
				print e

	if options.info and (options.service or options.node):
		if options.node:
			print '==================================================================================='
			print '[%s] system memory' % lists[0].ip
			do_ssh_command(lists[0].ip, 'free') # run once
			print '-----------------------------------------------------------------------------------'


		re_limit = re.compile("STAT limit_maxbytes ([0-9]+)")
		re_bytes = re.compile("STAT bytes ([0-9]+)")
		re_curr_conn = re.compile("STAT curr_connections ([0-9]+)")
		re_maxconns = re.compile("maxconns ([0-9]+)")

		last_node = None

		total_used = 0
		total_limit = 0
		for node in lists:
			try:
				if options.service and last_node != node.ip:
					if last_node != None:
						print 'TOTAL MEM: (%d/%d) %f%%' % (total_used, total_limit, total_used/total_limit*100)
						total_used = total_limit = 0

					print '==================================================================================='
					print '[%s] system memory' % node.ip
					do_ssh_command(node.ip, 'free') # run every server
					last_node = node.ip
					print '-----------------------------------------------------------------------------------'

				result = node.do_arcus_command('stats', timeout)
				m_limit = re_limit.search(result)
				m_bytes = re_bytes.search(result)
				m_curr_conn = re_curr_conn.search(result)

				result = node.do_arcus_command('config maxconns', timeout)
				m_maxconns = re_maxconns.search(result)

				#if m_limit == None or m_bytes == None or m_maxconns == None or m_curr_conn == None: # 1.6 not support maxconns
				if m_limit == None or m_bytes == None or m_curr_conn == None:
					print '%s\t\tstats failed!!' % (node)
					continue
				
				limit = int(m_limit.groups()[0]) / 1024 / 1024
				used = int(m_bytes.groups()[0]) / 1024 / 1024
				curr_conn = int(m_curr_conn.groups()[0])

				if m_maxconns == None:
					maxconns = 10000
				else:
					maxconns = int(m_maxconns.groups()[0])

				print '%s\t\tMEM: (%d/%d) %f%%, CONN: (%d/%d)' % (node, used, limit, used/limit*100, curr_conn, maxconns)
				total_used += used
				total_limit += limit

			except Exception, e:
				print '%s\t\tFAILED!!' % (node)
				print e
				continue
				

		print 'TOTAL MEM: (%d/%d) %f%%' % (total_used, total_limit, total_used/total_limit*100)



	if options.info and not options.service and not options.node: # brief report per cloud
		grand_total_used = 0
		grand_total_limit = 0
		grand_total_instances = 0

		for item in zoo_caches:
			zoo = item[0]
			caches = item[1]

			print '==================================================================================='
			print '## ' + zoo.address
			for cache in caches:

				lists = zoo.get_arcus_node_of_code(cache, '')

				re_limit = re.compile("STAT limit_maxbytes ([0-9]+)")
				re_bytes = re.compile("STAT bytes ([0-9]+)")
				re_curr_conn = re.compile("STAT curr_connections ([0-9]+)")
				re_maxconns = re.compile("maxconns ([0-9]+)")

				total_used = 0
				total_limit = 0
				for node in lists:
					try:
						if node.ip in remap:
							print '## vpn remap %s -> %s' % (node.ip, remap[node.ip])
							node.ip = remap[node.ip]

						result = node.do_arcus_command('stats', timeout)
						m_limit = re_limit.search(result)
						m_bytes = re_bytes.search(result)
						m_curr_conn = re_curr_conn.search(result)

						result = node.do_arcus_command('config maxconns', timeout)
						m_maxconns = re_maxconns.search(result)

						#if m_limit == None or m_bytes == None or m_maxconns == None or m_curr_conn == None: # 1.6 not support maxconns
						if m_limit == None or m_bytes == None or m_curr_conn == None:
							print '%s\t\tstats failed!!' % (node)
							continue
						
						limit = int(m_limit.groups()[0]) / 1024 /  1024
						used = int(m_bytes.groups()[0]) / 1024 / 1024
						curr_conn = int(m_curr_conn.groups()[0])

						if m_maxconns == None:
							maxconns = 10000
						else:
							maxconns = int(m_maxconns.groups()[0])

						total_used = total_used + used;
						total_limit = total_limit + limit;

					except Exception, e:
						print '%s\t\tFAILED!!' % (node)
						print e
						continue
						

				#print ('[%s] %d instances, (%d/%d) %f%%' % (cache, len(lists), total_used, total_limit, total_used/total_limit*100))
				print '[%s] %d instances, %dM memory' % (cache, len(lists), total_limit)
				grand_total_limit += total_limit
				grand_total_used += total_used
				grand_total_instances += len(lists)
		
		
		#print ('TOTAL %d instances, (%d/%d)M memory' % (grand_total_instances, grand_total_used, grand_total_limit grand_total_used/grand_total_limit*100))
		print 'TOTAL %d instances, %dM memory' % (grand_total_instances, grand_total_limit)
				


	if options.dump_script:
		re_limit = re.compile("STAT limit_maxbytes ([0-9]+)")
		re_bytes = re.compile("STAT bytes ([0-9]+)")
		re_curr_conn = re.compile("STAT curr_connections ([0-9]+)")
		re_maxconns = re.compile("maxconns ([0-9]+)")

		last_node = None

		total_used = 0
		total_limit = 0
		for node in lists:
			try:
				result = node.do_arcus_command('stats', timeout)
				m_limit = re_limit.search(result)
				m_bytes = re_bytes.search(result)
				m_curr_conn = re_curr_conn.search(result)

				result = node.do_arcus_command('config maxconns', timeout)
				m_maxconns = re_maxconns.search(result)

				#if m_limit == None or m_bytes == None or m_maxconns == None or m_curr_conn == None: # 1.6 not support maxconns
				if m_limit == None or m_bytes == None or m_curr_conn == None:
					print '%s\t\tstats failed!!' % (node)
					continue
				
				limit = int(m_limit.groups()[0]) / 1024 / 1024
				used = int(m_bytes.groups()[0]) / 1024 / 1024
				curr_conn = int(m_curr_conn.groups()[0])

				if m_maxconns == None:
					maxconns = 10000
				else:
					maxconns = int(m_maxconns.groups()[0])

				total_used += used
				total_limit += limit

			except Exception, e:
				print '%s\t\tFAILED!!' % (node)
				print e
				continue

			file_name = 'start_mem_%s.sh' % node.code
			script_fh = open(file_name, 'w')
			if os.path.getsize(file_name) == 0:
				script_fh.write('#!/bin/bash\n')
				os.chmod(file_name, 0755)

			start_script = '%s/bin/memcached -v -o 60 -r -m%d -R5 -p %s -d -c %d -U 0 -D: -b 8192 -u %s -t 6 -E %s/lib/default_engine.so -X %s/lib/syslog_logger.so -X %s/lib/ascii_scrub.so -z %s\n' % (HOME_DIR, limit, node.port, maxconns, USER, HOME_DIR, HOME_DIR, HOME_DIR, node.zk_addr)

			script_fh.write(start_script)

	if options.prefix:

		def print_stats(prefix, stats, is_total=False):
			result = ""
			printed_count = 0
			for current_prefix, prefix_stats in stats.items():
				if prefix == 'all' or current_prefix.startswith(prefix) or (current_prefix=='<null>' and prefix=='null'):
					printed_count += 1
					heading = "PREFIX %-10s " % (current_prefix)
					result += heading
					for key, value in prefix_stats.items():
						if key == 'time' and is_total:
							continue
						if key in ['tsz', 'lcs', 'scs', 'bcs', 'bps', 'pfs', 'gps']:
							result += "\n" + " "*(len(heading))
						if key in ['bps', 'pfs']:
							result += " "*12
						try:
							result += "%s %7d "% (key, value)
						except KeyError:
							# Some version of arcus-memcached does not print 'inc' and 'dec'
							pass
					result += "\n"
			if printed_count > 0:
				print(result)
			else:
				print("(no result)")


		def merge_stats(total_stats, node_stats):
			for prefix, stats in node_stats.items():
				if prefix not in total_stats:
					total_stats[prefix] = OrderedDict()
				for key, value in node_stats[prefix].items():
					total_stats[prefix][key] = total_stats[prefix].get(key, 0) + value

		def collect_stats(node, command):
			"""
			Returns:
			{ 'prefix1': OrderedDict[('key1', value1), ('key2', value2)...], ... }
			"""
			try:
				result = node.do_arcus_command(command, timeout)
			except Exception as e:
				print('%s\t\tFAILED!!' % (node))
				print(e)
				return {}

			node_stats = {}

			for line in result.splitlines():
				if not line.startswith("PREFIX"):
					continue

				tokens = line.split()
				current_prefix = tokens[1]

				prefix_stats = OrderedDict()

				for i in range(2, len(tokens), 2):
					key = tokens[i]
					value = int(tokens[i+1])
					prefix_stats[key] = value

				node_stats[current_prefix] = prefix_stats

			return node_stats

		prefixes_total = {}
		detail_total = {}

		for node in lists:
			print(node)

			node_stats = collect_stats(node, 'stats prefixes')
			print_stats(options.prefix, node_stats)
			merge_stats(prefixes_total, node_stats)

			node_stats = collect_stats(node, 'stats detail dump')
			print_stats(options.prefix, node_stats)
			merge_stats(detail_total, node_stats)

		print('[Total]')
		print_stats(options.prefix, prefixes_total, is_total=True)
		print_stats(options.prefix, detail_total, is_total=True)
