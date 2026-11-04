@echo off
setlocal

rem ===========================================================================
rem HaniCore Bosch ME7.1.1 / 44F - compile and link.
rem
rem This produces the ABS/HEX only. tools\build_hanicore_me711.py turns
rem that into the 1 MiB image, and it is the thing to run - it also generates
rem the ROMSYS header, relocates the vector table, computes all three bootrom
rem sums and refuses to emit if any of its checks fail.
rem
rem SHARED CORE: hcts.c and hcconfig.c are compiled from directories OUTSIDE
rem this target. Keil resolves #include "x.h" from the SOURCE FILE's own
rem directory first and only then from INCDIR, and neither shared directory
rem holds an hctarget.h - so each shared file picks up THIS board's header.
rem That was verified against the compiler, not assumed.
rem ===========================================================================

set TARGET=hani_me711
rem BOARD (2026-10-24): tools\build\build_hanicore_me711.py --board sets these;
rem the defaults ARE the Porsche ME7.1.1 build, as before.
if "%HC_BLD%"=="" set HC_BLD=build
if "%HC_LNP%"=="" set HC_LNP=linker_me711.lnp
if "%HC_PINDESC%"=="" set HC_PINDESC=hc_pin_desc_bosch_me711
set KEIL_BIN=C:\Keil\C166\BIN
rem FW  = the portable firmware (everything outside targets\).
rem INC = every directory a unit may include from. Header names are unique
rem across this set (tools\lib\hcpaths.py checks), so the search order
rem does not matter. No portable directory holds an hctarget.h: THIS
rem board's header is found here, which is how a portable unit gets the
rem right board. reg167.h / intrins.h come from the Keil installation
rem (C:\Keil\C166\INC) - the ME7.1.1 image uses no ME7.5 header.
set FW=..\..
set INC=%HC_BLD%;.;system;asic;hal;comms;engine;control;diagnostics;nvm;generated;%FW%\config;%FW%\engine;%FW%\control;%FW%\sensors;%FW%\diagnostics;%FW%\comms;%FW%\hal;%FW%\generated

if not exist %HC_BLD% mkdir %HC_BLD%

echo [HaniCore ME711] Building %TARGET% - Bosch ME7.1.1, RESETDIAG_V1
echo [HaniCore ME711] Outputs stay in %CD%\build

"%KEIL_BIN%\C166.EXE" system\hcmain_me711.c MOD167 SMALL RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcmain_me711.obj) PRINT(%HC_BLD%\hcmain_me711.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" asic\hcasic.c MOD167 SMALL RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcasic.obj) PRINT(%HC_BLD%\hcasic.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" asic\hcasicframe.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcasicframe.obj) PRINT(%HC_BLD%\hcasicframe.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" asic\hcasicstart.c MOD167 SMALL RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcasicstart.obj) PRINT(%HC_BLD%\hcasicstart.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" asic\hcumkom.c MOD167 SMALL RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcumkom.obj) PRINT(%HC_BLD%\hcumkom.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" system\hcpower.c MOD167 SMALL OBJECT(%HC_BLD%\hcpower.obj) PRINT(%HC_BLD%\hcpower.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

rem V79: native ASIC I/O, run-on, CJ120, LSU - FAR code (NCODE is full), XRAM data
"%KEIL_BIN%\C166.EXE" asic\hcio711.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcio711.obj) PRINT(%HC_BLD%\hcio711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" hal\hcdbwmotor711.c MOD167 MEDIUM OBJECT(%HC_BLD%\hcdbwmotor711.obj) PRINT(%HC_BLD%\hcdbwmotor711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" generated\hcvec_me711.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcvec_me711.obj) PRINT(%HC_BLD%\hcvec_me711.lst) INCDIR(%INC%)
if errorlevel 1 goto fail
rem the unclaimed-trap catch-alls are assembly stubs (FCODE)
"%KEIL_BIN%\A166.EXE" generated\hcvecstub_me711.a66 SET(SMALL) OBJECT(%HC_BLD%\hcvecstub_me711.obj) PRINT(%HC_BLD%\hcvecstub_me711.lst)
if errorlevel 1 goto fail

rem V81: far thunks into NCODE for the MEDIUM (FCODE) modules - hcfarbridge.h
"%KEIL_BIN%\C166.EXE" diagnostics\hcdiag711.c MOD167 MEDIUM OBJECT(%HC_BLD%\hcdiag711.obj) PRINT(%HC_BLD%\hcdiag711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" system\hcfar_me711.c MOD167 SMALL OBJECT(%HC_BLD%\hcfar_me711.obj) PRINT(%HC_BLD%\hcfar_me711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail

"%KEIL_BIN%\C166.EXE" hal\hchal_me711.c MOD167 SMALL %HC_C4X% OBJECT(%HC_BLD%\hchal_me711.obj) PRINT(%HC_BLD%\hchal_me711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" engine\hctrig_me711.c MOD167 SMALL OBJECT(%HC_BLD%\hctrig_me711.obj) PRINT(%HC_BLD%\hctrig_me711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" system\hcprofile711.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcprofile711.obj) PRINT(%HC_BLD%\hcprofile711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" system\hcdefaults711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) OBJECT(%HC_BLD%\hcdefaults711.obj) PRINT(%HC_BLD%\hcdefaults711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" engine\hcdeadline_plan711.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcdeadline_plan711.obj) PRINT(%HC_BLD%\hcdeadline_plan711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" hal\hcroutes711.c MOD167 MEDIUM OBJECT(%HC_BLD%\hcroutes711.obj) PRINT(%HC_BLD%\hcroutes711.lst) INCDIR(%INC%)
if errorlevel 1 goto fail
"%KEIL_BIN%\C166.EXE" engine\hcload711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) OBJECT(%HC_BLD%\hcload711.obj) PRINT(%HC_BLD%\hcload711.lst) INCDIR(%INC%)
if errorlevel 1 goto fail
"%KEIL_BIN%\C166.EXE" engine\hcdeadline711.c MOD167 SMALL OBJECT(%HC_BLD%\hcdeadline711.obj) PRINT(%HC_BLD%\hcdeadline711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" engine\hcsched_dry.c MOD167 SMALL OBJECT(%HC_BLD%\hcsched_dry.obj) PRINT(%HC_BLD%\hcsched_dry.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" system\hcsafety.c MOD167 SMALL OBJECT(%HC_BLD%\hcsafety.obj) PRINT(%HC_BLD%\hcsafety.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem the K-line transport - PEC6 receive, S0TBINT replies - FAR code
"%KEIL_BIN%\C166.EXE" comms\hcserial711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) OBJECT(%HC_BLD%\hcserial711.obj) PRINT(%HC_BLD%\hcserial711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem the runtime monitor's cold half (stack scans) - FAR code
"%KEIL_BIN%\C166.EXE" system\hcrtmon711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) OBJECT(%HC_BLD%\hcrtmon711.obj) PRINT(%HC_BLD%\hcrtmon711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" diagnostics\hcbench.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcbench.obj) PRINT(%HC_BLD%\hcbench.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V94: the VAG/KWP vehicle entry - FAR code; the shared core is pure
"%KEIL_BIN%\C166.EXE" %FW%\comms\hckline.c MOD167 MEDIUM %HC_KLDEF% RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hckline.obj) PRINT(%HC_BLD%\hckline.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V96: the wideband core - FAR code, pure (SFR-free, host-tested)
"%KEIL_BIN%\C166.EXE" %FW%\sensors\hcwb.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcwb.obj) PRINT(%HC_BLD%\hcwb.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: the cam PATTERN core - FAR code, pure (SFR-free, host-tested); the two cams in XRAM
"%KEIL_BIN%\C166.EXE" %FW%\engine\hccam.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hccam.obj) PRINT(%HC_BLD%\hccam.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" comms\hckwp_me711.c MOD167 MEDIUM %HC_KWPDEF% RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hckwp_me711.obj) PRINT(%HC_BLD%\hckwp_me711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: boost control - the pure core (hcldr.c) and its ME7.1.1 module (thunks) - FAR code
"%KEIL_BIN%\C166.EXE" %FW%\control\hcldr.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcldr.obj) PRINT(%HC_BLD%\hcldr.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" control\hcboost711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcboost711.obj) PRINT(%HC_BLD%\hcboost711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: idle speed control - the pure core and its ME7.1.1 module - FAR code
"%KEIL_BIN%\C166.EXE" %FW%\control\hcidle.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcidle.obj) PRINT(%HC_BLD%\hcidle.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" %FW%\control\hcknock.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcknock.obj) PRINT(%HC_BLD%\hcknock.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" engine\hcknock711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcknock711.obj) PRINT(%HC_BLD%\hcknock711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" %FW%\control\hcvvt.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcvvt.obj) PRINT(%HC_BLD%\hcvvt.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" control\hcvvt711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcvvt711.obj) PRINT(%HC_BLD%\hcvvt711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" control\hcidle711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcidle711.obj) PRINT(%HC_BLD%\hcidle711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem 2026-10-14: fan, A/C, programmable outputs, oil pressure - FAR code
"%KEIL_BIN%\C166.EXE" control\hcaux711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcaux711.obj) PRINT(%HC_BLD%\hcaux711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: ignition timing corrections (coolant, intake air) - FAR code
"%KEIL_BIN%\C166.EXE" engine\hcigncorr711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcigncorr711.obj) PRINT(%HC_BLD%\hcigncorr711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V98: the engine-control layer (load, DFCO, closed loop, motorsport, priming) - FAR code
"%KEIL_BIN%\C166.EXE" engine\hcengctl711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcengctl711.obj) PRINT(%HC_BLD%\hcengctl711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V99: the engine event ring + lambda dynamics - FAR code
"%KEIL_BIN%\C166.EXE" diagnostics\hcevlog711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcevlog711.obj) PRINT(%HC_BLD%\hcevlog711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: the check-engine lamp policy - FAR code
"%KEIL_BIN%\C166.EXE" %FW%\diagnostics\hccel.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hccel.obj) PRINT(%HC_BLD%\hccel.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: transient fuel - the pure core and its ME7.1.1 module - FAR code
"%KEIL_BIN%\C166.EXE" %FW%\engine\hctrans.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hctrans.obj) PRINT(%HC_BLD%\hctrans.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" engine\hctrans711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hctrans711.obj) PRINT(%HC_BLD%\hctrans711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: trouble codes - the pure core and its ME7.1.1 module - FAR code
"%KEIL_BIN%\C166.EXE" %FW%\diagnostics\hcdtc.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcdtc.obj) PRINT(%HC_BLD%\hcdtc.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" diagnostics\hcdtc711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcdtc711.obj) PRINT(%HC_BLD%\hcdtc711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V97: engine protection - the pure core and its ME7.1.1 module - FAR code
"%KEIL_BIN%\C166.EXE" %FW%\control\hclimp.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hclimp.obj) PRINT(%HC_BLD%\hclimp.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" control\hclimp711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hclimp711.obj) PRINT(%HC_BLD%\hclimp711.lst) INCDIR(%INC%)
"%KEIL_BIN%\C166.EXE" control\hcxfn711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcxfn711.obj) PRINT(%HC_BLD%\hcxfn711.lst) INCDIR(%INC%)
"%KEIL_BIN%\C166.EXE" comms\hccan711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hccan711.obj) PRINT(%HC_BLD%\hccan711.lst) INCDIR(%INC%)
"%KEIL_BIN%\C166.EXE" control\hcvss711.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcvss711.obj) PRINT(%HC_BLD%\hcvss711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
rem V93: ETB endpoint calibration + PID autotune - FAR code, thunks via hcfarbridge.h
"%KEIL_BIN%\C166.EXE" control\hcetbcal.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcetbcal.obj) PRINT(%HC_BLD%\hcetbcal.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" hal\hcfresh711.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcfresh711.obj) PRINT(%HC_BLD%\hcfresh711.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
"%KEIL_BIN%\C166.EXE" nvm\hcnvm.c MOD167 SMALL OBJECT(%HC_BLD%\hcnvm.obj) PRINT(%HC_BLD%\hcnvm.lst) INCDIR(%INC%)
if errorlevel 1 goto :fail
if errorlevel 1 goto :fail

if errorlevel 1 goto :fail

rem --- shared core -----------------------------------------------------------
"%KEIL_BIN%\C166.EXE" %FW%\comms\hcts.c MOD167 SMALL RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcts.obj) PRINT(%HC_BLD%\hcts.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\config\hcconfig.c MOD167 SMALL OBJECT(%HC_BLD%\hcconfig.obj) PRINT(%HC_BLD%\hcconfig.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\engine\hcengine.c MOD167 SMALL %HC_C4X% OBJECT(%HC_BLD%\hcengine.obj) PRINT(%HC_BLD%\hcengine.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\control\hcmainrelay.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcmainrelay.obj) PRINT(%HC_BLD%\hcmainrelay.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\control\hcfuelpump.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hcfuelpump.obj) PRINT(%HC_BLD%\hcfuelpump.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\control\hc_dbw.c MOD167 SMALL OBJECT(%HC_BLD%\hc_dbw.obj) PRINT(%HC_BLD%\hc_dbw.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

rem --- the universal configuration layer -----------------------------------
rem GENERATED sources plus the two hand-written units above them. The pin
rem descriptor compiled here is THIS BOARD'S - hc_pin_desc_bosch_me711.c -
rem and exactly one descriptor may ever be linked into an image.
"%KEIL_BIN%\C166.EXE" %FW%\generated\hc_config_generated.c MOD167 SMALL OBJECT(%HC_BLD%\hc_config_generated.obj) PRINT(%HC_BLD%\hc_config_generated.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\generated\hc_pin_descriptor.c MOD167 MEDIUM RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hc_pin_descriptor.obj) PRINT(%HC_BLD%\hc_pin_descriptor.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\generated\%HC_PINDESC%.c MOD167 SMALL OBJECT(%HC_BLD%\%HC_PINDESC%.obj) PRINT(%HC_BLD%\%HC_PINDESC%.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\config\hc_validation.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hc_validation.obj) PRINT(%HC_BLD%\hc_validation.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\config\hc_config_manager.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hc_config_manager.obj) PRINT(%HC_BLD%\hc_config_manager.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\generated\hc_presets.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) RENAMECLASS(NDATA0=XNDATA0) OBJECT(%HC_BLD%\hc_presets.obj) PRINT(%HC_BLD%\hc_presets.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\config\hc_route.c MOD167 MEDIUM DEFINE(HC_FAR_BRIDGE) OBJECT(%HC_BLD%\hc_route.obj) PRINT(%HC_BLD%\hc_route.lst) INCDIR(%INC%)
if errorlevel 1 goto fail
"%KEIL_BIN%\C166.EXE" %FW%\engine\hc_airfuel.c MOD167 SMALL OBJECT(%HC_BLD%\hc_airfuel.obj) PRINT(%HC_BLD%\hc_airfuel.lst) INCDIR(%INC%)
if errorlevel 1 goto fail

"%KEIL_BIN%\C166.EXE" %FW%\engine\hc_plan.c MOD167 SMALL OBJECT(%HC_BLD%\hc_plan.obj) PRINT(%HC_BLD%\hc_plan.lst) INCDIR(%INC%)
if errorlevel 1 goto fail


"%KEIL_BIN%\A166.EXE" system\start_me711.a66 SET(SMALL%HC_ASET%) OBJECT(%HC_BLD%\start_me711.obj) PRINT(%HC_BLD%\start_me711.lst)
if errorlevel 1 goto fail

if errorlevel 1 goto fail

rem L166 RETURN CODES: 0 clean, 1 warnings, 2 errors, 3 fatal. This step stops
rem on 2 and above, NOT on 1, because hcvec_me711.c is deliberately compiled
rem MOD167 MEDIUM and the locater says WARNING L14 INCOMPATIBLE MEMORY MODEL
rem about it on every single link.
rem
rem ACCEPTING WARNINGS HERE WOULD GO ON TO ACCEPT "L5 SECTION LOCATED OUTSIDE
rem CLASS AREA", which is the one tripwire that tells this project its code
rem class just overflowed - the maintainer's design notes is about the
rem three releases where that number was wrong. So the allowlist is NOT here:
rem tools/build_hanicore_me711.py re-reads this output and refuses any warning
rem that is not exactly the L14 naming HCVEC_ME711.
"%KEIL_BIN%\L166.EXE" @%HC_LNP%
if errorlevel 2 goto fail

rem RANGE starts at the VECTAB park address so nothing is clipped. OH166 emits
rem relative to the RANGE start; the Python builder knows that 0 means 0x840000.
rem 2026-10-25: up to 0x86FFFF - SA9 joined FCODE on 2026-10-15 but this
rem range stayed at SA8, so a section the linker put in SA9 was dropped from
rem the image (it ran into blank flash). The builder now checks every CODE
rem section of the map against the image.
"%KEIL_BIN%\OH166.EXE" %HC_BLD%\%TARGET%.abs H167 RANGE(0x830000-0x86FFFF)
if errorlevel 1 goto fail

if exist %HC_BLD%\%TARGET%.H86 copy /Y %HC_BLD%\%TARGET%.H86 %HC_BLD%\%TARGET%.hex >nul
if exist %HC_BLD%\%TARGET%.HEX copy /Y %HC_BLD%\%TARGET%.HEX %HC_BLD%\%TARGET%.hex >nul

echo [HaniCore ME711] Link complete.
exit /b 0

:fail
echo [HaniCore ME711] Build failed.
exit /b 1
