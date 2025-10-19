#!/usr/bin/env python3
'''Test configuration and verify system requirements'''

import sys
import subprocess
from pathlib import Path


def check_ffmpeg():
    '''Check if FFmpeg is installed'''
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f'✓ FFmpeg is installed: {version}')
            return True
        else:
            print('✗ FFmpeg is installed but returned an error')
            return False
    except FileNotFoundError:
        print('✗ FFmpeg is not installed')
        print('  Install with: sudo apt install ffmpeg')
        return False
    except Exception as e:
        print(f'✗ Error checking FFmpeg: {e}')
        return False


def check_config():
    '''Check if config file exists'''
    config_path = Path('config.yaml')
    if config_path.exists():
        print(f'✓ Config file exists: {config_path}')
        return True
    else:
        print('✗ Config file not found: config.yaml')
        print('  Copy config.yaml.example to config.yaml and edit it')
        return False


def check_python_version():
    '''Check Python version'''
    version = sys.version_info
    if version.major == 3 and version.minor >= 13:
        print(f'✓ Python version: {version.major}.{version.minor}.{version.micro}')
        return True
    else:
        print(f'✗ Python version {version.major}.{version.minor}.{version.micro} is too old')
        print('  Requires Python 3.13 or newer')
        return False


def load_and_validate_config():
    '''Load config and validate'''
    try:
        import yaml
        
        config_path = Path('config.yaml')
        if not config_path.exists():
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Check cameras
        cameras = config.get('cameras', [])
        if not cameras:
            print('✗ No cameras defined in config')
            return False
        
        print(f'✓ Found {len(cameras)} camera(s) in config')
        
        # Check each camera
        for cam in cameras:
            name = cam.get('name', 'unnamed')
            rtsp_url = cam.get('rtsp_url', '')
            output_dir = cam.get('output_dir', '')
            
            if not rtsp_url:
                print(f'  ✗ Camera {name}: missing rtsp_url')
                return False
            
            if not output_dir:
                print(f'  ✗ Camera {name}: missing output_dir')
                return False
            
            # Check if output directory exists or can be created
            output_path = Path(output_dir)
            if not output_path.exists():
                print(f'  ! Camera {name}: output directory does not exist: {output_dir}')
                print('    Will be created automatically')
            else:
                print(f'  ✓ Camera {name}: output directory exists')
        
        return True
        
    except ImportError:
        print('✗ PyYAML not installed')
        print('  Run: uv sync')
        return False
    except Exception as e:
        print(f'✗ Error loading config: {e}')
        return False


def main():
    '''Main test function'''
    print('=== cams-manager Configuration Test ===\n')
    
    checks = [
        ('Python Version', check_python_version),
        ('FFmpeg', check_ffmpeg),
        ('Config File', check_config),
        ('Config Validation', load_and_validate_config),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print(f'✗ {name} check failed: {e}')
            results.append(False)
        print()
    
    # Summary
    print('=' * 40)
    if all(results):
        print('✓ All checks passed! Ready to run cams-manager')
        print('\nRun with: uv run cams-manager')
        return 0
    else:
        print('✗ Some checks failed. Please fix the issues above.')
        return 1


if __name__ == '__main__':
    sys.exit(main())

