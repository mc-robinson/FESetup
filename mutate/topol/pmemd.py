#  Copyright (C) 2014-2016  Hannes H Loeffler
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
#  For full details of the license please see the COPYING file
#  that should have come with this distribution.

r"""
Create perturbed topologies for pmemd14.
"""


__revision__ = "$Id$"


import os

from FESetup import const, errors, logger
from FESetup.mutate import util

import amber 



class PertTopology(object):

    def __init__(self, FE_sub_type, sc_type, ff, con_morph, atoms_initial,
                 atoms_final, lig_initial, lig_final, atom_map,
                 reverse_atom_map, zz_atoms, gaff):

        self.FE_sub_type = FE_sub_type
        self.sc_type = sc_type
        self.ff = ff
        self.gaff = gaff
        self.con_morph = con_morph
        self.atoms_initial = atoms_initial
        self.atoms_final = atoms_final
        self.lig_initial = lig_initial
        self.lig_final = lig_final
        self.atom_map = atom_map
        self.reverse_atom_map = reverse_atom_map
        self.zz_atoms = zz_atoms

        self.frcmod0 = None
        self.frcmod1 = None

        self.initial_dummies = not all([a.atom for a in atom_map.keys()])
        self.final_dummies = not all([a.atom for a in atom_map.values()])


    def setup(self, curr_dir, lig_morph, cmd1, cmd2):

        patch_parms = []

        if self.FE_sub_type[:8] == 'softcore':
            util.amber_input(self.atoms_initial, self.atoms_final,
                             self.atom_map, self.sc_type, self.FE_sub_type,
                             True)

            state0, state1 = util.amber_softcore(lig_morph, self.lig_final,
                                                 self.atom_map)

            pert0_info, pert1_info = None, None
            ow_add = '_sc'
        elif self.FE_sub_type == 'dummy' or self.FE_sub_type == 'dummy2':
            state0 = lig_morph
            state1, pert0_info, pert1_info = \
                    amber.dummy(lig_morph, self.con_morph,
                                self.lig_final, self.atom_map)
            ow_add = '_dummy'
        else:
            raise NotImplementedError


        mol2_0 = os.path.join(curr_dir, const.MORPH_NAME + ow_add + '0' +
                              const.MOL2_EXT)
        util.write_mol2(state0, mol2_0, resname = const.LIGAND0_NAME)

        frcmod0 = os.path.join(curr_dir, const.MORPH_NAME + ow_add +
                               '0.frcmod')

        mol2_1 = os.path.join(curr_dir, const.MORPH_NAME + ow_add + '1' +
                              const.MOL2_EXT)
        util.write_mol2(state1, mol2_1, resname = const.LIGAND1_NAME)

        frcmod1 = os.path.join(curr_dir, const.MORPH_NAME + ow_add +
                               '1.frcmod')


        lig = self.ff.Ligand(const.MORPH_NAME, start_file=mol2_0,
                             start_fmt='mol2', frcmod=frcmod0,
                             gaff=self.gaff)

        lig.set_atomtype(self.gaff)

        lig._parmchk(mol2_0, 'mol2', frcmod0)
        lig._parmchk(mol2_1, 'mol2', frcmod1)

        lig._parm_overwrite = 'pmemd' + ow_add

        if self.FE_sub_type == 'softcore' or self.FE_sub_type == 'softcore3':
            lig.prepare_top()
            lig.leap.add_mol(mol2_1, 'mol2', frcmod1)
            lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)

        if self.FE_sub_type == 'softcore2' or self.FE_sub_type == 'dummy2':
            ow_add = '_int'

            if self.FE_sub_type == 'dummy2':
                f = True
            else:
                f = False

            int_state = util.transfer_charges(state0, state1, self.atom_map, f)

            mol2_int = os.path.join(curr_dir, const.MORPH_NAME + ow_add +
                                    const.MOL2_EXT)
            util.write_mol2(int_state, mol2_int, resname = const.INT_NAME)

            lig = self.ff.Ligand(const.MORPH_NAME, start_file=mol2_0,
                                 start_fmt='mol2', frcmod=frcmod0,
                                 gaff=self.gaff)
            lig.set_atomtype(self.gaff)
            lig._parm_overwrite = 'pmemd_sc_2step_1'

            if self.initial_dummies:
                patch_parms.append( (lig._parm_overwrite,
                                     ':%s' % const.LIGAND0_NAME,
                                     ':%s' % const.INT_NAME) )

            lig.prepare_top(pert=pert0_info)
            # intermediate state does never have dummies
            lig.leap.add_mol(mol2_int, 'mol2', frcmod1)
            lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)

            lig = self.ff.Ligand(const.MORPH_NAME, start_file=mol2_int,
                                 start_fmt='mol2', frcmod=frcmod1,
                                 gaff=self.gaff)
            lig.set_atomtype(self.gaff)
            lig._parm_overwrite = 'pmemd_sc_2step_2'

            if self.final_dummies:
                patch_parms.append( (lig._parm_overwrite,
                                     ':%s' % const.INT_NAME, 
                                     ':%s' % const.LIGAND1_NAME) )

            # intermediate state does never have dummies
            lig.prepare_top()
            lig.leap.add_mol(mol2_1, 'mol2', frcmod0, pert=pert1_info)
            lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)
        # FIXME: residue name will be both the same
        elif self.FE_sub_type == 'softcore3':
            lig = self.ff.Ligand(const.MORPH_NAME, start_file=mol2_0,
                                 start_fmt='mol2', frcmod=frcmod0,
                                 gaff=self.gaff)
            lig.set_atomtype(self.gaff)
            lig._parm_overwrite = 'pmemd_decharge' + ow_add

            lig.prepare_top()
            lig.leap.add_mol(mol2_0, 'mol2', frcmod0)
            lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)

            lig = self.ff.Ligand(const.MORPH_NAME, start_file=mol2_1,
                                 start_fmt='mol2', frcmod=frcmod1,
                                 gaff=self.gaff)
            lig.set_atomtype(self.gaff)
            lig._parm_overwrite = 'pmemd_recharge' + ow_add

            lig.prepare_top()
            lig.leap.add_mol(mol2_1, 'mol2', frcmod1)
            lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)
        elif self.FE_sub_type == 'dummy':
            lig.prepare_top(pert=pert0_info)
            lig.leap.add_mol(mol2_1, 'mol2', frcmod1, pert=pert1_info)
            lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)

        self.frcmod0 = frcmod0
        self.frcmod1 = frcmod1

        if self.FE_sub_type == 'dummy' or self.FE_sub_type == 'dummy2':
            for prm in patch_parms:
                util.patch_parmtop(prm[0] + lig.TOP_EXT, "", prm[1], prm[2])


    def create_coords(self, curr_dir, dir_name, lig_morph, pdb_file, system,
                      cmd1, cmd2, boxdims):

        patch_parms = []

        if self.FE_sub_type[:8] == 'softcore':
            util.amber_input(self.atoms_initial, self.atoms_final,
                             self.atom_map, self.sc_type, self.FE_sub_type,
                             False)

            state0, state1 = \
                    util.amber_softcore(lig_morph, self.lig_final,
                                        self.atom_map)

            pert0_info, pert1_info = None, None
            ow_add = '_sc'
        elif self.FE_sub_type == 'dummy' or self.FE_sub_type == 'dummy2':
            state0 = lig_morph
            state1, pert0_info, pert1_info = \
                    amber.dummy(lig_morph, self.con_morph,
                                self.lig_final, self.atom_map)

            ow_add = '_dummy'
        else:
            raise NotImplementedError

        mol2_0 = os.path.join(curr_dir, const.MORPH_NAME + ow_add + '0' +
                              const.MOL2_EXT)
        util.write_mol2(state0, mol2_0, resname = const.LIGAND0_NAME)

        mol2_1 = os.path.join(curr_dir, const.MORPH_NAME + ow_add + '1' +
                              const.MOL2_EXT)
        util.write_mol2(state1, mol2_1, resname = const.LIGAND1_NAME)

        com = self.ff.Complex(pdb_file, mol2_0)
        com.box_dims = boxdims
        com.ligand_fmt = 'mol2'
        com.frcmod = self.frcmod0
        com._parm_overwrite = 'pmemd' + ow_add

        if self.FE_sub_type == 'softcore' or self.FE_sub_type == 'softcore3':
            com.prepare_top(gaff=self.gaff)
            com.leap.add_mol(mol2_1, 'mol2', self.frcmod1)
            com.create_top(boxtype='set', addcmd=cmd1 + cmd2)

        if self.FE_sub_type == 'softcore2' or self.FE_sub_type == 'dummy2':
            ow_add = '_int'
            
            if self.FE_sub_type == 'dummy2':
                f = True
            else:
                f = False

            int_state = util.transfer_charges(state0, state1, self.atom_map, f)

            mol2_int = os.path.join(curr_dir, const.MORPH_NAME + ow_add +
                                    const.MOL2_EXT)
            util.write_mol2(int_state, mol2_int, resname = const.INT_NAME)

            com = self.ff.Complex(pdb_file, mol2_0)
            com.box_dims = boxdims
            com.ligand_fmt = 'mol2'
            com.frcmod = self.frcmod0
            com._parm_overwrite = 'pmemd_sc_2step_1'

            if self.initial_dummies:
                patch_parms.append( (com._parm_overwrite,
                                     ':%s' % const.LIGAND0_NAME, 
                                     ':%s' % const.INT_NAME) )

            com.prepare_top(gaff=self.gaff, pert=pert0_info)
            # intermediate state does never have dummies
            com.leap.add_mol(mol2_int, 'mol2', self.frcmod1)
            com.create_top(boxtype='set', addcmd=cmd1 + cmd2)

            com = self.ff.Complex(pdb_file, mol2_int)
            com.box_dims = boxdims
            com.ligand_fmt = 'mol2'
            com.frcmod = self.frcmod1
            com._parm_overwrite = 'pmemd_sc_2step_2'

            if self.final_dummies:
                patch_parms.append( (com._parm_overwrite,
                                     ':%s' % const.INT_NAME,
                                     ':%s' % const.LIGAND1_NAME) )

            # intermediate state does never have dummies
            com.prepare_top(gaff=self.gaff)
            com.leap.add_mol(mol2_1, 'mol2', self.frcmod0, pert=pert1_info)
            com.create_top(boxtype='set', addcmd=cmd1 + cmd2)

        # FIXME: residue name will be both the same
        elif self.FE_sub_type == 'softcore3':
            com = self.ff.Complex(pdb_file, mol2_0)
            com.box_dims = boxdims
            com.ligand_fmt = 'mol2'
            com.frcmod = self.frcmod0
            com._parm_overwrite = 'pmemd_decharge' + ow_add

            com.prepare_top(gaff=self.gaff)
            com.leap.add_mol(mol2_0, 'mol2', self.frcmod0)
            com.create_top(boxtype='set', addcmd=cmd1 + cmd2)

            com = self.ff.Complex(pdb_file, mol2_1)
            com.box_dims = boxdims
            com.ligand_fmt = 'mol2'
            com.frcmod = self.frcmod1
            com._parm_overwrite = 'pmemd_recharge' + ow_add

            com.prepare_top(gaff=self.gaff)
            com.leap.add_mol(mol2_1, 'mol2', self.frcmod1)
            com.create_top(boxtype='set', addcmd=cmd1 + cmd2)
        elif self.FE_sub_type == 'dummy':
            com.prepare_top(gaff=self.gaff, pert=pert0_info)
            com.leap.add_mol(mol2_1, 'mol2', self.frcmod1, pert=pert1_info)
            com.create_top(boxtype='set', addcmd=cmd1 + cmd2)


        if self.FE_sub_type == 'dummy' or self.FE_sub_type == 'dummy2':
            for prm in patch_parms:
                util.patch_parmtop(prm[0] + com.TOP_EXT, "", prm[1], prm[2])


