#ifndef HCTRIG_ANGLE_REF_ME711_H
#define HCTRIG_ANGLE_REF_ME711_H

/* Converts the decoder's 0..3599 physical crank coordinate into the engine's
   0..7199 cycle coordinate. A positive offset advances engine zero relative
   to the physical trigger reference; phase selection remains independent.
   Configuration must constrain reference_offset_x10 to -3599..3599. */
unsigned int trg_engine_angle_x10(unsigned int physical_angle_x10,
                                  unsigned char phase,
                                  int reference_offset_x10);

#endif /* HCTRIG_ANGLE_REF_ME711_H */