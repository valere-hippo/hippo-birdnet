import os
import sys
import csv
import subprocess
import shutil
import uuid
import tempfile

from django.shortcuts import render
from django.conf import settings
from .models import AudioFile

from django.http import HttpResponse
from openpyxl import Workbook


def convert_audio_to_wav(input_path, output_path):
    """
    Utilise ffmpeg pour convertir un fichier audio en WAV 16-bit PCM mono 48kHz.
    """
    try:
        subprocess.run([
            'ffmpeg',
            '-y',                # overwrite output if exists
            '-i', input_path,    # input file
            '-ac', '1',          # mono
            '-ar', '48000',      # 48kHz
            '-sample_fmt', 's16',# 16-bit PCM
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def upload_audio(request):
    error = None

    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('audio')

        if not uploaded_files:
            return render(request, 'upload.html', {'error': "Keine Dateien ausgewählt."})

        # Vider le dossier des résultats
        results_dir = os.path.join(settings.BASE_DIR, 'BirdNET-Analyzer', 'results')
        if os.path.exists(results_dir):
            shutil.rmtree(results_dir)
        os.makedirs(results_dir)

        results = []

        for uploaded_file in uploaded_files:
            # Sauvegarde initiale du fichier (tel qu'uploadé)
            audio_model = AudioFile.objects.create(audio=uploaded_file)
            original_path = audio_model.audio.path

            # Créer un fichier temporaire pour le WAV converti
            temp_wav_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.wav")

            # Convertir vers WAV compatible BirdNET
            conversion_success = convert_audio_to_wav(original_path, temp_wav_path)
            if not conversion_success:
                results.append({
                    'name': uploaded_file.name,
                    'data': [],
                    'error': 'Fehler bei der Konvertierung in WAV.'
                })
                continue

            # Analyse avec BirdNET
            try:
                subprocess.run([
                    sys.executable, '-m', 'birdnet_analyzer.analyze',
                    '--output', results_dir,
                    '--lat', '48.85',
                    '--lon', '2.35',
                    '--week', '28',
                    '--sensitivity', '0.5',
                    '--threads', '2',
                    temp_wav_path
                ],
                    check=True,
                    cwd=os.path.join(settings.BASE_DIR, 'BirdNET-Analyzer'),
                    env={**os.environ, 'PYTHONPATH': os.path.join(settings.BASE_DIR, 'BirdNET-Analyzer')}
                )
            except subprocess.CalledProcessError as e:
                results.append({
                    'name': uploaded_file.name,
                    'data': [],
                    'error': f"Fehler bei der Analyse: {e}"
                })
                continue

            # Chercher le fichier de résultats
            basename = os.path.splitext(os.path.basename(temp_wav_path))[0]
            txt_path = None
            for file in os.listdir(results_dir):
                if file.endswith('.txt') and basename in file:
                    txt_path = os.path.join(results_dir, file)
                    break

            # Lire les résultats
            data = []
            if txt_path and os.path.exists(txt_path):
                try:
                    with open(txt_path, newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f, delimiter='\t')
                        for row in reader:
                            data.append(row)
                except Exception as e:
                    results.append({
                        'name': uploaded_file.name,
                        'data': [],
                        'error': f"Fehler beim Lesen der Datei: {e}"
                    })
                    continue

            results.append({
                'name': uploaded_file.name,
                'data': data,
                'error': None
            })

        return render(request, 'result.html', {'results': results})

    return render(request, 'upload.html')

def export_excel(request):
    results_dir = os.path.join(settings.BASE_DIR, 'BirdNET-Analyzer', 'results')
    files = [f for f in os.listdir(results_dir) if f.endswith('.txt')]

    if not files:
        return HttpResponse("Keine Ergebnisse gefunden.", status=404)

    wb = Workbook()
    wb.remove(wb.active)

    for file in files:
        file_path = os.path.join(results_dir, file)
        try:
            with open(file_path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter='\t')
                rows = list(reader)

                if not rows:
                    continue

                sheet_name = os.path.splitext(file)[0][:31]
                ws = wb.create_sheet(title=sheet_name)

                for row in rows:
                    ws.append(row)
        except Exception as e:
            continue

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=BirdNET_Ergebnisse.xlsx'
    wb.save(response)

    return response
