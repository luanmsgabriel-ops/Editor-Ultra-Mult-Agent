"""Grave a interface real por meio do WebSocket do OBS Studio."""

import argparse
import json
import os
import sys


def recording_status(client):
    response = client.get_record_status()
    return {
        'recording': bool(response.output_active),
        'paused': bool(response.output_paused),
        'duration_ms': response.output_duration
    }


def inspect(client):
    scene = client.get_current_program_scene().current_program_scene_name
    sources = client.get_scene_item_list(scene).scene_items
    return {
        'scene': scene,
        'sources': [
            {'name': item['sourceName'], 'enabled': item['sceneItemEnabled']}
            for item in sources
        ],
        **recording_status(client),
    }


def start(client, expected_scene=None, required_sources=()):
    setup = inspect(client)
    if expected_scene is not None and setup['scene'] != expected_scene:
        raise ValueError(f"A cena atual é {setup['scene']!r}. Selecione {expected_scene!r} no OBS.")
    enabled = {item['name'] for item in setup['sources'] if item['enabled']}
    missing = set(required_sources) - enabled
    if missing:
        raise ValueError(f'Fontes ausentes ou desativadas na cena: {", ".join(sorted(missing))}.')
    if setup['recording']:
        raise ValueError('O OBS já está gravando.')
    client.start_record()
    state = recording_status(client)
    if not state['recording']:
        raise RuntimeError('O OBS recebeu o comando, mas ainda não confirmou a gravação. Consulte inspect.')
    return {**setup, **state}


def stop(client):
    if not recording_status(client)['recording']:
        raise ValueError('O OBS não tem uma gravação em andamento.')
    completed = client.stop_record()
    return {'recording': False, 'output_path': completed.output_path}


def connect(host, port, timeout=5):
    try:
        from obsws_python import ReqClient
    except ImportError as exc:
        raise ValueError('Instale a dependência opcional com python -m pip install obsws-python.') from exc
    password = os.environ.get('OBS_WEBSOCKET_PASSWORD', '')
    return ReqClient(host=host, port=port, password=password, timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=4455)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('inspect', help='Consulta a cena em programa, as fontes e o estado da gravação.')
    record = commands.add_parser('start', help='Inicia a gravação da cena em programa.')
    record.add_argument('--scene', help='Confere o nome da cena antes de iniciar.')
    record.add_argument('--require-source', action='append', default=[], help='Confere uma fonte ativa.')
    commands.add_parser('stop', help='Encerra a gravação e devolve o caminho informado pelo OBS.')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('A porta deve estar entre 1 e 65535.')
    try:
        client = connect(args.host, args.port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'Conexão com o OBS falhou ({type(exc).__name__}). Confira endereço e credencial.',
              file=sys.stderr)
        return 1
    try:
        if args.command == 'inspect':
            outcome = inspect(client)
        elif args.command == 'start':
            outcome = start(client, args.scene, args.require_source)
        else:
            outcome = stop(client)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'Requisição ao OBS falhou ({type(exc).__name__}). Consulte inspect antes de repetir.',
              file=sys.stderr)
        return 1
    finally:
        client.disconnect()
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
