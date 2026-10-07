#!/usr/bin/env python3
"""Учебная копия CD-диска с 3D-снимком зубов (КБКТ) для шага 9.

Берёт настоящий снимок, прореживает и уменьшает его, вычищает всё, что указывает на человека, и
раскладывает так, как это выглядит на диске клиники: программа-просмотрщик (без самих .exe), её папки
и один большой DICOM-файл глубоко внутри. Имя и дата рождения — учебного пациента.

Нужны: pydicom, numpy, pylibjpeg, pylibjpeg-libjpeg (только для подготовки, участникам не нужны).
Запуск: python3 dev/make_ct_disk.py <путь к исходному .dcm>
"""
import sys
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ct-disk-copy"
FRAME_STEP = 8     # каждый 8-й срез: 400 → 50
SCALE = 2          # 700×700 → 350×350
STUDY_DATE = "20250918"
CT_NAME = f"CT_{STUDY_DATE}-101530-112"
PATIENT_DIR = "20250918-101200-001"

# Поля, которые называют человека, место или время, — заменяем учебными или очищаем.
REPLACE = {"PatientName": "NOVAK^ALEKSANDER", "PatientID": "MC-0048213", "PatientBirthDate": "19840312",
           "PatientAge": "041Y", "PatientSex": "M", "StudyDate": STUDY_DATE, "SeriesDate": STUDY_DATE,
           "ContentDate": STUDY_DATE, "StudyTime": "101530", "SeriesTime": "101530", "ContentTime": "101530"}
CLEAR = ["InstanceCreationDate", "InstanceCreationTime", "AcquisitionDate", "AcquisitionDateTime",
         "AcquisitionTime", "AccessionNumber", "InstitutionName", "InstitutionAddress", "ReferringPhysicianName",
         "StationName", "StudyDescription", "SeriesDescription", "OperatorsName", "PerformingPhysicianName",
         "DeviceSerialNumber", "StudyID", "OtherPatientIDs", "OtherPatientNames", "PatientAddress",
         "PatientComments", "StudyComments", "RequestingPhysician", "SoftwareVersions"]


def main(src):
    ds = pydicom.dcmread(src)
    vol = ds.pixel_array                      # (кадры, строки, столбцы)
    idx = list(range(0, vol.shape[0], FRAME_STEP))
    small = vol[idx][:, ::SCALE, ::SCALE].astype(vol.dtype)  # прореживание без интерполяции — значения те же

    ds.remove_private_tags()
    for k, v in REPLACE.items():
        setattr(ds, k, v)
    for k in CLEAR:
        if k in ds:
            ds.data_element(k).value = ""

    ds.NumberOfFrames = len(idx)
    ds.Rows, ds.Columns = small.shape[1], small.shape[2]
    pf = ds.PerFrameFunctionalGroupsSequence
    ds.PerFrameFunctionalGroupsSequence = Sequence([pf[i] for i in idx])
    # размер пикселя и толщина среза — с учётом прореживания
    for groups in [ds.SharedFunctionalGroupsSequence[0]] + list(ds.PerFrameFunctionalGroupsSequence):
        if "PixelMeasuresSequence" in groups:
            pm = groups.PixelMeasuresSequence[0]
            if "PixelSpacing" in pm:
                pm.PixelSpacing = [float(x) * SCALE for x in pm.PixelSpacing]
            if "SliceThickness" in pm:
                pm.SliceThickness = float(pm.SliceThickness) * FRAME_STEP
    for uid_field in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID"):
        if uid_field in ds:
            setattr(ds, uid_field, generate_uid())
    ds.PixelData = small.tobytes()
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = ds.SOPClassUID
    meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = meta

    data = OUT / "TheiaViewer" / "TheiaViewerData" / "Patient" / PATIENT_DIR / "CT" / "Work" / CT_NAME
    data.mkdir(parents=True, exist_ok=True)
    dst = data / f"{CT_NAME}.dcm"
    ds.save_as(dst, enforce_file_format=True)
    # остальное, как на диске клиники: автозапуск и папка программы-просмотрщика (без программы)
    (OUT / "autorun.inf").write_text("[autorun]\nopen=setup.exe\nicon=setup.exe\n", encoding="utf-8")
    viewer = OUT / "TheiaViewer" / "TheiaViewer" / "Bin64"
    viewer.mkdir(parents=True, exist_ok=True)
    (viewer / "ПРОГРАММА НЕ ВКЛЮЧЕНА.txt").write_text(
        "На настоящем диске здесь лежит программа-просмотрщик клиники (только для Windows).\n"
        "В учебную копию она не включена. Снимок — в папке TheiaViewerData.\n", encoding="utf-8")
    print(f"готово: {len(idx)} срезов {small.shape[1]}×{small.shape[2]}, {dst.stat().st_size // 1024 // 1024} МБ → {dst}")


if __name__ == "__main__":
    main(sys.argv[1])
