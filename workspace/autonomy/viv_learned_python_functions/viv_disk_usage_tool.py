# Autonomously synthesized by Viv via Python Neural Cortex
import os
import sys
import shutil

def check_l_drive_free_space():
    '''Diagnostic tool built by Viv using learned Python neurons.'''
    drive_path = 'L:/'
    total, used, free = shutil.disk_usage(drive_path)
    free_gb = free // (1024 * 1024 * 1024)
    print(f'[VIV TOOL EXECUTION] L: Drive Free Space: {free_gb} GB')
    return free_gb

if __name__ == '__main__':
    check_l_drive_free_space()
