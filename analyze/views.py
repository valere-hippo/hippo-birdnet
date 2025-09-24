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

import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile


def convert_audio_to_wav(input_path, output_path):
    try:
        subprocess.run([
            'ffmpeg',
            '-y',
            '-i', input_path,
            '-ac', '1',
            '-ar', '48000',
            '-sample_fmt', 's16',
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def generate_spectrogram(wav_path, output_path):
    try:
        sr, y = wavfile.read(wav_path)
        y = y / np.max(np.abs(y))  # Normalisation

        plt.figure(figsize=(12, 4))
        plt.specgram(y, Fs=sr, NFFT=1024, noverlap=512, cmap='inferno')
        plt.xlabel("Zeit (s)")
        plt.ylabel("Frequenz (Hz)")
        plt.colorbar(label="Intensität (dB)")
        plt.title("Spektrogramm")

        plt.savefig(output_path, bbox_inches='tight', pad_inches=0.1)
        plt.close()
        return True
    except Exception as e:
        print("Fehler beim Erzeugen des Spektrogramms:", e)
        return False


def upload_audio(request):
    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('audio')

        if not uploaded_files:
            return render(request, 'upload.html', {'error': "Keine Dateien ausgewählt."})

        results_dir = os.path.join(settings.BASE_DIR, 'BirdNET-Analyzer', 'results')
        media_spectro_dir = os.path.join(settings.MEDIA_ROOT, 'spectrograms')

        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(media_spectro_dir, exist_ok=True)

        shutil.rmtree(results_dir)
        os.makedirs(results_dir)

        results = []

        for uploaded_file in uploaded_files:
            audio_model = AudioFile.objects.create(audio=uploaded_file)
            original_path = audio_model.audio.path
            audio_url = audio_model.audio.url

            temp_wav_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.wav")

            conversion_success = convert_audio_to_wav(original_path, temp_wav_path)
            if not conversion_success:
                results.append({
                    'name': uploaded_file.name,
                    'data': [],
                    'error': 'Fehler bei der Konvertierung in WAV.',
                    'audio_url': None,
                    'spectrogram': None
                })
                continue

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
                    'error': f"Fehler bei der Analyse: {e}",
                    'audio_url': audio_url,
                    'spectrogram': None
                })
                continue

            basename = os.path.splitext(os.path.basename(temp_wav_path))[0]
            txt_path = None
            for file in os.listdir(results_dir):
                if file.endswith('.txt') and basename in file:
                    txt_path = os.path.join(results_dir, file)
                    break

            data = []
            if txt_path and os.path.exists(txt_path):
                try:
                    with open(txt_path, newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f, delimiter='\t')
                        for row in reader:
                            if "Begin Path" in row:
                                del row["Begin Path"]
                            data.append(row)
                except Exception as e:
                    results.append({
                        'name': uploaded_file.name,
                        'data': [],
                        'error': f"Fehler beim Lesen der Datei: {e}",
                        'audio_url': audio_url,
                        'spectrogram': None
                    })
                    continue

            # Spektrogramm erzeugen
            spectro_filename = f"{uuid.uuid4().hex}.png"
            spectro_output_path = os.path.join(media_spectro_dir, spectro_filename)
            spectrogram_rel_url = f"media/spectrograms/{spectro_filename}"

            spectrogram_created = generate_spectrogram(temp_wav_path, spectro_output_path)

            results.append({
                'name': uploaded_file.name,
                'data': data,
                'error': None,
                'audio_url': audio_url,
                'spectrogram': spectrogram_rel_url if spectrogram_created else None
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

                headers = rows[0]
                if "Begin Path" in headers:
                    index = headers.index("Begin Path")
                    for row in rows:
                        del row[index]

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
