import adsk.core
import adsk.fusion
import os
import traceback


PROJECT_DIR = '/private/var/hiddenadmin/Desktop/BX Project/hardware/scanner-gun-v2'
EXPORT_DIR = os.path.join(PROJECT_DIR, 'exports')
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'fusion360')
LOG_PATH = os.path.join(OUTPUT_DIR, 'build_log.txt')
F3D_PATH = os.path.join(OUTPUT_DIR, 'scanner_gun_v2_editable.f3d')
STEP_PATH = os.path.join(OUTPUT_DIR, 'scanner_gun_v2_editable.step')


def write_log(message):
    with open(LOG_PATH, 'a', encoding='utf-8') as stream:
        stream.write(message + '\n')


def add_reference_parameters(design):
    params = design.userParameters
    values = [
        ('camera_panel_width', '37.75 mm', 'Measured camera PCB width'),
        ('camera_panel_height', '37.75 mm', 'Measured camera PCB height'),
        ('camera_hole_spacing', '24 mm', 'Camera square hole centre spacing'),
        ('button_panel_width', '29.92 mm', 'Measured button PCB width'),
        ('button_panel_height', '29.92 mm', 'Measured button PCB height'),
        ('button_hole_spacing', '24 mm', 'Button square hole centre spacing'),
        ('insert_outer_diameter', '3.9 mm', 'Measured M3 heat-set insert OD'),
        ('insert_length', '2.85 mm', 'Measured M3 heat-set insert length'),
        ('insert_pilot_diameter', '3.70 mm', 'Current printed pilot diameter'),
        ('panel_screw_clearance', '3.40 mm', 'M3 panel screw clearance'),
        ('cable_diameter', '2.8 mm', 'Target cable diameter'),
        ('cable_channel_width', '6.6 mm', 'Internal cable channel width'),
        ('cable_channel_depth', '4.4 mm', 'Internal cable channel depth'),
        ('shell_wall', '2.4 mm', 'Nominal shell wall'),
        ('dock_clearance_per_side', '1.2 mm', 'Dock clearance on each side'),
    ]
    for name, expression, comment in values:
        if not params.itemByName(name):
            params.add(
                name,
                adsk.core.ValueInput.createByString(expression),
                'mm',
                comment,
            )


def import_and_convert(root, name, filename, translation_cm):
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(
        translation_cm[0], translation_cm[1], translation_cm[2]
    )
    occurrence = root.occurrences.addNewComponent(transform)
    component = occurrence.component
    component.name = name

    source_path = os.path.join(EXPORT_DIR, filename)
    write_log(f'Importing {source_path}')
    imported = component.meshBodies.add(
        source_path,
        adsk.fusion.MeshUnits.MillimeterMeshUnit,
    )
    if not imported or imported.count == 0:
        raise RuntimeError(f'Fusion could not import {filename}')

    mesh_body = imported.item(0)
    mesh_body.name = name + ' Source Mesh'
    write_log(
        f'  mesh closed={mesh_body.isClosed}, oriented={mesh_body.isOriented}, '
        f'volume_cm3={mesh_body.volume:.6f}'
    )

    convert_features = component.features.meshConvertFeatures
    convert_input = convert_features.createInput([mesh_body])
    convert_input.meshConvertMethodType = (
        adsk.fusion.MeshConvertMethodTypes.PrismaticMeshConvertMethodType
    )
    convert_input.meshConvertOperationType = (
        adsk.fusion.MeshConvertOperationTypes.BaseFeatureMeshConvertOperationType
    )

    try:
        convert_features.add(convert_input)
        method = 'Prismatic'
    except Exception:
        write_log('  Prismatic conversion failed; using exact faceted BRep fallback')
        write_log(traceback.format_exc())
        convert_input = convert_features.createInput([mesh_body])
        convert_input.meshConvertMethodType = (
            adsk.fusion.MeshConvertMethodTypes.FacetedMeshConvertMethodType
        )
        convert_input.meshConvertOperationType = (
            adsk.fusion.MeshConvertOperationTypes.BaseFeatureMeshConvertOperationType
        )
        convert_features.add(convert_input)
        method = 'Faceted fallback'

    if component.bRepBodies.count == 0:
        raise RuntimeError(f'No solid body was created for {name}')

    for index in range(component.bRepBodies.count):
        body = component.bRepBodies.item(index)
        body.name = name if index == 0 else f'{name} Body {index + 1}'
    mesh_body.isLightBulbOn = False
    write_log(
        f'  conversion={method}, solid_bodies={component.bRepBodies.count}'
    )
    return occurrence


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(LOG_PATH, 'w', encoding='utf-8') as stream:
            stream.write('Scanner Gun V2 Fusion build\n')

        document = app.documents.add(
            adsk.core.DocumentTypes.FusionDesignDocumentType
        )
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.DirectDesignType
        root = design.rootComponent
        root.name = 'Scanner Gun V2 Editable Assembly'
        add_reference_parameters(design)

        specifications = [
            ('01 Left Shell', 'scanner_left_shell_v2.stl', (0.0, 0.0, 0.0)),
            ('02 Right Shell', 'scanner_right_shell_v2.stl', (0.0, 0.0, 0.0)),
            ('03 Head Dock', 'scanner_dock_v2.stl', (10.5, 0.0, 10.0)),
            ('04 Mount Test', 'scanner_mount_test_v2.stl', (20.0, 0.0, 10.0)),
        ]
        for name, filename, translation in specifications:
            import_and_convert(root, name, filename, translation)
            adsk.doEvents()

        export_manager = design.exportManager
        write_log(f'Exporting Fusion archive: {F3D_PATH}')
        if not export_manager.execute(
            export_manager.createFusionArchiveExportOptions(F3D_PATH, root)
        ):
            raise RuntimeError('Fusion archive export failed')

        write_log(f'Exporting STEP: {STEP_PATH}')
        if not export_manager.execute(
            export_manager.createSTEPExportOptions(STEP_PATH, root)
        ):
            raise RuntimeError('STEP export failed')

        app.activeViewport.fit()
        write_log('BUILD COMPLETE')
        ui.messageBox(
            'Fusion editable files created successfully:\n\n'
            + F3D_PATH + '\n' + STEP_PATH,
            'Scanner Gun V2',
        )
    except Exception:
        error_text = traceback.format_exc()
        try:
            write_log('BUILD FAILED')
            write_log(error_text)
        except Exception:
            pass
        ui.messageBox(error_text, 'Scanner Gun V2 build failed')


def stop(context):
    pass
