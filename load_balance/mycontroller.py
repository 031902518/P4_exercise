#!/usr/bin/env python3
import argparse
import os
import sys
from time import sleep

import grpc
# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
from p4runtime_lib.switch import ShutdownAllSwitchConnections
from p4runtime_lib.error_utils import printGrpcError
import p4runtime_lib.helper
import p4runtime_lib.bmv2



def write_ecmp_group_rules(p4info_helper, ingress_sw, dst_ip_addr,
                            ecmp_base, ecmp_max):
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ecmp_group",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.set_ecmp_select",
        action_params={
            "ecmp_base": ecmp_base,
            "ecmp_count": ecmp_max
        })
    ingress_sw.WriteTableEntry(table_entry)


def write_ecmp_nhop_rules(p4info_helper, ingress_sw, ecmp_select, 
                        nex_hop_ip, nex_hop_mac, egress_port):
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ecmp_nhop",
        match_fields={
            "meta.ecmp_select": ecmp_select
        },
        action_name="MyIngress.set_nhop",
        action_params={
            "nhop_dmac": nex_hop_mac,
            "nhop_ipv4": nex_hop_ip,
            "port" : egress_port
        })
    ingress_sw.WriteTableEntry(table_entry)


def write_send_frame_rules(p4info_helper, ingress_sw, egress_port, smac):
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyEgress.send_frame",
        match_fields={
            "standard_metadata.egress_port": egress_port
        },
        action_name="MyEgress.rewrite_mac",
        action_params={
            "smac": smac
        })
    ingress_sw.WriteTableEntry(table_entry)







def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Create a switch connection object for s1 and s2;
        # this is backed by a P4Runtime gRPC connection.
        # Also, dump all P4Runtime messages sent to switch to given txt files.
        s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s1',
            address='127.0.0.1:50051',
            device_id=0,
            proto_dump_file='logs/s1-p4runtime-requests.txt')
        s2 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s2',
            address='127.0.0.1:50052',
            device_id=1,
            proto_dump_file='logs/s2-p4runtime-requests.txt')
        # Create a switch connection object for s3
        s3 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s3',
            address='127.0.0.1:50053',
            device_id=2,
            proto_dump_file='logs/s3-p4runtime-requests.txt')

        # Send master arbitration update message to establish this controller as
        # master (required by P4Runtime before performing any other write operation)
        s1.MasterArbitrationUpdate()
        s2.MasterArbitrationUpdate()
        s3.MasterArbitrationUpdate()

        # Install the P4 program on the switches
        s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s1")
        s2.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s2")
        s3.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s3")
        # s1
        write_ecmp_group_rules(p4info_helper=p4info_helper,ingress_sw=s1,
            dst_ip_addr="10.0.0.1",ecmp_base=0,ecmp_max=2)
        write_ecmp_nhop_rules(p4info_helper=p4info_helper,ingress_sw=s1,
            ecmp_select=0,nex_hop_ip="10.0.2.2",nex_hop_mac="00:00:00:00:01:02",egress_port=2)
        write_ecmp_nhop_rules(p4info_helper=p4info_helper,ingress_sw=s1,
            ecmp_select=1,nex_hop_ip="10.0.3.3",nex_hop_mac="00:00:00:00:01:03",egress_port=3)
        write_send_frame_rules(p4info_helper=p4info_helper,ingress_sw=s1,
            egress_port=2,smac="00:00:00:01:02:00")
        write_send_frame_rules(p4info_helper=p4info_helper,ingress_sw=s1,
            egress_port=3,smac="00:00:00:01:03:00")

        #s2
        write_ecmp_group_rules(p4info_helper=p4info_helper,ingress_sw=s2,
            dst_ip_addr="10.0.2.2",ecmp_base=0,ecmp_max=1)
        write_ecmp_nhop_rules(p4info_helper=p4info_helper,ingress_sw=s2,
            ecmp_select=0,nex_hop_ip="10.0.2.2",nex_hop_mac="08:00:00:00:02:02",egress_port=1)
        write_send_frame_rules(p4info_helper=p4info_helper,ingress_sw=s2,
            egress_port=1,smac="00:00:00:02:01:00")
        
        #s3
        write_ecmp_group_rules(p4info_helper=p4info_helper,ingress_sw=s3,
            dst_ip_addr="10.0.3.3",ecmp_base=0,ecmp_max=1)
        write_ecmp_nhop_rules(p4info_helper=p4info_helper,ingress_sw=s3,
            ecmp_select=0,nex_hop_ip="10.0.3.3",nex_hop_mac="08:00:00:00:03:03",egress_port=1)
        write_send_frame_rules(p4info_helper=p4info_helper,ingress_sw=s3,
            egress_port=1,smac="00:00:00:03:01:00")

        # Print the tunnel counters every 2 seconds
        while True:
            sleep(2)           

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/load_balance.p4.p4info.txt')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/load_balance.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print("\np4info file not found: %s\nHave you run 'make'?" % args.p4info)
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print("\nBMv2 JSON file not found: %s\nHave you run 'make'?" %
              args.bmv2_json)
        parser.exit(1)
    main(args.p4info, args.bmv2_json)