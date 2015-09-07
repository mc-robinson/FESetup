#  Copyright (C) 2012-2014  Hannes H Loeffler, Julien Michel
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
Create perturbed topologies for Sire.
"""


__revision__ = "$Id$"


import os, sys

import Sire.Mol
import Sire.MM
import Sire.Units

from chemistry.amber.readparm import AmberParm

from FESetup import const, errors, logger
from FESetup.mutate import util



class PertTopology(object):

    def __init__(self, FE_sub_type, sc_type, ff, con_morph, atoms_initial,
                 atoms_final, lig_initial, lig_final, atom_map,
                 reverse_atom_map, zz_atoms):

        self.ff = ff
        self.atoms_final = atoms_final
        self.lig_initial = lig_initial
        self.lig_final = lig_final
        self.atom_map = atom_map
        self.reverse_atom_map = reverse_atom_map
        self.zz_atoms = zz_atoms
        
        self.frcmod = None


    def setup(self, curr_dir, lig_morph, cmd1, cmd2):
        """
        """

        mol2 = os.path.join(curr_dir, const.MORPH_NAME + const.MOL2_EXT)
        util.write_mol2(lig_morph, mol2, False, self.zz_atoms)

        # create a new Ligand from the MOL2
        self.frcmod = os.path.join(curr_dir, const.MORPH_NAME + '.frcmod')

        # FIXME: Ligand class needs some redesign!
        lig = self.ff.Ligand(const.MORPH_NAME, '', start_file = mol2,
                             start_fmt = 'mol2', frcmod = self.frcmod)

        # prevent antechamber from running over the MOL2 file
        lig.set_atomtype('gaff')

        lig._parmchk(mol2, 'mol2', self.frcmod)
        lig.create_top(boxtype = '', addcmd = cmd1 + cmd2)

        patch_element(lig.amber_top, lig_morph, self.lig_initial,
                      self.lig_final, self.atom_map)

        lig.flex()

        # to get bonds, angles and dihedrals we reload the morph top/crd and
        # assume ligand is first molecule
        top, crd = lig.get_topcrd()

        try:
            molecules = Sire.IO.Amber().readCrdTop(crd, top)[0]
        except UserWarning as error:
            raise errors.SetupError('error opening %s/%s: %s' %
                                    (crd, top, error) )

        new_morph = molecules.first().molecule()

        noangles = False
        shrinkbonds = False
        make_pert_file(lig_morph, new_morph, self.lig_initial,
                       self.lig_final, self.atoms_final, self.atom_map,
                       self.reverse_atom_map, self.zz_atoms,
                       noangles, shrinkbonds)


    def create_coords(self, curr_dir, dir_name, lig_morph, pdb_file, system,
                      cmd1, cmd2):
        """
        """

        mol2 = os.path.join(curr_dir, dir_name, const.MORPH_NAME +
                            const.MOL2_EXT)
        util.write_mol2(lig_morph, mol2, False, self.zz_atoms)

        # we should now have a new MOL2 with updated coordinates for the ligand
        # these will have to be 'pasted' into the system and new crd/top be
        # prepared
        com = self.ff.Complex(pdb_file, mol2)
        com.frcmod = self.frcmod

        com.ligand_fmt = 'mol2'
        com.create_top(boxtype = 'set',
                       addcmd = cmd1 + cmd2)

        patch_element(com.amber_top, lig_morph, self.lig_initial,
                      self.lig_final, self.atom_map)

        com.lig_flex()

        if type(system) == self.ff.Complex:
            com.prot_flex()


def patch_element(parmtop, lig_morph, lig_initial, lig_final, atom_map):
    """
    Patch masses and atomic numbers in a AMBER parmtop file.  Dummy atoms are
    created with a zero mass but MD requires finite masses.  Thus get the mass
    and atomic number from the respective other state.

    :param parmtop: filename of the parmtop file to be patched
    :type parmtop: string
    :param lig_morph: the morph molecule
    :type lig_morph: Sire.Mol.CutGroup
    :param lig_initial: the initial state molecule
    :type lig_initial: Sire.Mol.Molecule
    :param lig_final: the final state molecule
    :type lig_final: Sire.Mol.Molecule
    :param atom_map: the forward atom map
    :type atom_map: dict of_AtomInfo to _AtomInfo 
     """

    parm = AmberParm(parmtop)

    for idx, num in enumerate(parm.parm_data['ATOMIC_NUMBER']):
        if num < 0:
            midx = Sire.Mol.AtomIdx(idx)
            mname = lig_morph.select(midx).name()
            fidx = util.search_by_index(midx, atom_map)

            if mname.value().startsWith('DU'):
                atom = lig_final.select(fidx)
                mass = atom.property('mass').value()
            else:
                atom = lig_initial.select(midx)
                mass = max(atom.property('mass').value(),
                           lig_final.select(fidx).property('mass').value() )

            atnum = atom.property('element').nProtons()

            parm.parm_data['ATOMIC_NUMBER'][idx] = atnum
            parm.parm_data['MASS'][idx] = mass

    parm.overwrite = True
    parm.writeParm(parmtop)
 
    return


def _isSameDihedralPotential(ipot, fpot):
    """Helper function."""

    if ipot == "todefine" and fpot == "todefine":
        return True

    if ipot == "todefine" and fpot != "todefine":
        return False

    if ipot != "todefine" and fpot == "todefine":
        return False

    # Test is complicated because...for multi term dihedrals, they may
    # not be in the same order in the two lists of parameters
    for x in range(0, len(ipot), 3):
        ki = ipot[x]
        periodi = ipot[x+1]
        phasei = ipot[x+2]

        match = False

        for y in range(0, len(fpot), 3):
            kf = fpot[y]
            periodf = fpot[y+1]
            phasef = fpot[y+2]

            # JM bugfix Oct 13. Found a case where the morph and the initial
            # molecules have a different dihedral potential, but only because
            # the initial state has a null cos2phi potential which isn't
            # present in the morph.
            # NOTE: this first test will falsely mark dihedrals as same
#           if ki < sys.float_info.min or \
            if \
                   (abs(ki - kf) < sys.float_info.min and
                    abs(periodi - periodf) < sys.float_info.min and
                    abs(phasei - phasef) < sys.float_info.min):
                match = True
                break

        if not match:
            return False

    return True


def _isSameBondAnglePotential(ipot, fpot):
    """Helper function."""

    if ipot == "todefine" and fpot == "todefine":
        return True

    if ipot == "todefine" and fpot != "todefine":
        return False

    if ipot != "todefine" and fpot == "todefine":
        return False

    if (abs(ipot[0] - fpot[0]) > sys.float_info.min or
        abs(ipot[1] - fpot[1]) > sys.float_info.min):
        return False
    else:
        return True


def make_pert_file(old_morph, new_morph, lig_initial, lig_final,
                   atoms_final, atom_map, reverse_atom_map, zz_atoms,
                   turnoffdummyangles, shrinkdummybonds):

    """
    Create a perturbation file for Sire.

    :param old_morph: the original morph molecule
    :type old_morph: Sire.Mol.Molecule
    :param new_morph: a new morph molecule for manipulations
    :type new_morph: Sire.Mol.Molecule
    :param lig_initial: the initial state molecule
    :type lig_initial: Sire.Mol.Molecule
    :param lig_final: the final state molecule
    :type lig_final: Sire.Mol.Molecule
    :param atoms_final: set of final atoms
    :type atoms_final: Sire.Mol.Selector_Atom
    :param atom_map: the forward atom map
    :type atom_map: dict of _AtomInfo to _AtomInfo
    :param reverse_atom_map: the reverse atom map
    :type reverse_atom_map: dict of _AtomInfo to _AtomInfo
    :param zz_atoms: rename atoms in list to 'zz' to circumvent leap valency check
    :type zz_atoms: list of Sire.Mol.AtomName
    :param turnoffdummyangles: turn off dummy angles
    :type turnoffdummyangles: bool
    :param shrinkdummybonds: shrink dummy bonds
    :type shrinkdummybonds: bool
    :raises: SetupError
    """

    old_morph = old_morph.edit()
    atom_num = 0

    # finalise morph
    for iinfo, finfo in atom_map.items():
        if not finfo.atom:
            final_charge = 0.0 * Sire.Units.mod_electron
            final_lj = Sire.MM.LJParameter(0.0 * Sire.Units.angstrom,
                                           0.0 * Sire.Units.kcal_per_mol)
            final_type = "du"
        else:
            base = atoms_final.select(finfo.index)
            final_charge = base.property("charge")
            final_lj = base.property("LJ")
            final_type = "%s" % base.property("ambertype")

        new = old_morph.atom(iinfo.index) # AtomEditor
        new.setProperty('final_charge', final_charge)
        new.setProperty('final_LJ', final_lj)
        new.setProperty('final_ambertype', final_type)

        old_morph = new.molecule()
    old_morph = old_morph.commit()

    pert_fname = const.MORPH_NAME + os.extsep + 'pert'
    logger.write('Writing perturbation file %s...\n' % pert_fname)

    pertfile = open(pert_fname, 'w')

    outstr = "version 1\n"
    outstr += "molecule %s\n" % (const.LIGAND_NAME)
    pertfile.write(outstr)

    # Write atom perts
    morph_natoms = old_morph.nAtoms()

    for atom in old_morph.atoms():
        if ( (atom.property("initial_ambertype") !=
              atom.property("final_ambertype") )
             or (atom.property("initial_charge") !=
                 atom.property("final_charge") )
             or (atom.property("initial_LJ") !=
                 atom.property("final_LJ") ) ):
            outstr = "\tatom\n"
            outstr += "\t\tname %s\n" % atom.name().value()
            outstr += "\t\tinitial_type    %s\n" % atom.property(
                "initial_ambertype")
            outstr += "\t\tfinal_type      %s\n" % atom.property(
                "final_ambertype")
            outstr += "\t\tinitial_charge %8.5f\n" % atom.property(
                "initial_charge").value()
            outstr += "\t\tfinal_charge   %8.5f\n" % atom.property(
                "final_charge").value()
            outstr += "\t\tinitial_LJ     %8.5f %8.5f\n" % (
                atom.property("initial_LJ").sigma().value(),
                atom.property("initial_LJ").epsilon().value())
            outstr += "\t\tfinal_LJ       %8.5f %8.5f\n" % (
                atom.property("final_LJ").sigma().value(),
                atom.property("final_LJ").epsilon().value())
            outstr += "\tendatom\n"

            pertfile.write(outstr)


    # Figure out which bond, angles, dihedrals have their potential variable
    params_initial = lig_initial.property("amberparameters")
    bonds_initial = params_initial.getAllBonds()
    angles_initial = params_initial.getAllAngles()
    dihedrals_initial = params_initial.getAllDihedrals()
    impropers_initial = params_initial.getAllImpropers()

    params_final = lig_final.property("amberparameters")
    bonds_final = params_final.getAllBonds()
    angles_final = params_final.getAllAngles()
    dihedrals_final = params_final.getAllDihedrals()
    impropers_final = params_final.getAllImpropers()

    params_morph = new_morph.property("amberparameters")
    bonds_morph = params_morph.getAllBonds()
    angles_morph = params_morph.getAllAngles()
    dihedrals_morph = params_morph.getAllDihedrals()
    impropers_morph = params_morph.getAllImpropers()


    # For each pair of atoms making a bond in the morph we find
    # the equivalent pair in the initial topology. If there
    # are no matches this should be because one of the two atoms is a dummy
    # atom. If not, this sounds like a bug and the code aborts.

    for bond in bonds_morph:
        mpot = params_morph.getParams(bond)

        idummy = False
        fdummy = False
        ipot = None

        at0 = new_morph.select(bond.atom0() )
        at1 = new_morph.select(bond.atom1() )

        at0i = at0.index()
        at1i = at1.index()

        for ibond in bonds_initial:
            iat0 = lig_initial.select(ibond.atom0() ).index()
            iat1 = lig_initial.select(ibond.atom1() ).index()

            if ( (at0i == iat0 and at1i == iat1) or
                 (at0i == iat1 and at1i == iat0) ):
                ipot = params_initial.getParams(ibond)
                break

        if not ipot:
            if (at0.name().value().startsWith("DU") or
                at1.name().value().startsWith("DU") ):
                ipot = "todefine"
                idummy = True
            else:
                raise errors.SetupError('Could not locate bond parameters for '
                                        'the final state. This is most likely '
                                        'because the atom mapping would open '
                                        'up a ring in the intial state. ')

        fpot = None

        map_at0 = util.search_atom(at0i, atom_map)
        map_at1 = util.search_atom(at1i, atom_map)

        for fbond in bonds_final:
            fat0 = lig_final.select(fbond.atom0() )
            fat1 = lig_final.select(fbond.atom1() )

            if ( (map_at0 == fat0 and map_at1 == fat1) or
                 (map_at0 == fat1 and map_at1 == fat0) ):
                fpot = params_final.getParams(fbond)
                break

        if fpot is None:
            if (not map_at0 or not map_at1):
                fpot = "todefine"
                fdummy = True
            else:
                raise errors.SetupError('Could not locate bond parameters for '
                                        'the final state. This is most likely '
                                        'because the atom mapping would open '
                                        'up a ring in the intial state.')
                                        

        samepotential = _isSameBondAnglePotential(ipot, fpot)


        if (not samepotential and
            ipot != "todefine" and
            not _isSameBondAnglePotential(ipot, mpot) ):
                if (at0.name().value() in zz_atoms or
                    at1.name().value() in zz_atoms):
                    samepotential = False
                else:
                    raise errors.SetupError('The initial and morph potentials '
                                            'are different, but the potential '
                                            'does not involve a dummy atom. '
                                            'This case is not handled by the '
                                            'code.')

        #
        # If either atom in the initial/final states is a dummy, then the
        # parameters are kept constant throughout the perturbation
        #
        if idummy and fdummy:
            raise errors.SetupError('BUG: Both the initial and final states '
                                    'involve dummy atoms. (bond)')
        elif idummy:
            ipot = fpot
        elif fdummy:
            fpot = ipot

        if (idummy or fdummy) or (not samepotential):
            i_force = ipot[0]
            i_eq = ipot[1]
            f_force = fpot[0]
            f_eq = fpot[1]

            if shrinkdummybonds and idummy:
                i_eq = 0.2 # Angstrom
            if shrinkdummybonds and fdummy:
                f_eq = 0.2 # Angstrom

            outstr = "\tbond\n"
            outstr += "\t\tatom0   %s\n" % at0.name().value()
            outstr += "\t\tatom1   %s\n" % at1.name().value()
            outstr += "\t\tinitial_force %s\n" % i_force
            outstr += "\t\tinitial_equil %s\n" % i_eq
            outstr += "\t\tfinal_force   %s\n" % f_force
            outstr += "\t\tfinal_equil   %s\n" % f_eq
            outstr += "\tendbond\n"

            pertfile.write(outstr)


    # Now angles...

    for angle in angles_morph:
        mpot = params_morph.getParams(angle)

        idummy = False
        fdummy = False
        ipot = None

        at0 = new_morph.select(angle.atom0() )
        at1 = new_morph.select(angle.atom1() )
        at2 = new_morph.select(angle.atom2() )

        at0i = at0.index()
        at1i = at1.index()
        at2i = at2.index()

        for iangle in angles_initial:
            iat0 = lig_initial.select(iangle.atom0() ).index()
            iat1 = lig_initial.select(iangle.atom1() ).index()
            iat2 = lig_initial.select(iangle.atom2() ).index()

            if ( (at0i == iat0 and at1i == iat1 and at2i == iat2) or
                 (at0i == iat2 and at1i == iat1 and at2i == iat0) ):
                ipot = params_initial.getParams(iangle)
                break

        if ipot is None:
            if (at0.name().value().startsWith("DU") or
                at1.name().value().startsWith("DU") or
                at2.name().value().startsWith("DU") ):
                ipot = "todefine"
                idummy = True
            else:
                raise errors.SetupError('can not determine ipot for angle %s ' %
                                        angle)

        fpot = None
        map_at0 = util.search_atom(at0i, atom_map)
        map_at1 = util.search_atom(at1i, atom_map)
        map_at2 = util.search_atom(at2i, atom_map)

        for fangle in angles_final:
            fat0 = lig_final.select(fangle.atom0() )
            fat1 = lig_final.select(fangle.atom1() )
            fat2 = lig_final.select(fangle.atom2() )

            if ( (map_at0 == fat0 and map_at1 == fat1 and map_at2 == fat2) or
                 (map_at0 == fat2 and map_at1 == fat1 and map_at2 == fat0) ):
                fpot = params_final.getParams(fangle)
                break

        if fpot is None:
            if (not map_at0 or not map_at1 or not map_at2):
                fpot = "todefine"
                fdummy = True
            else:
                raise errors.SetupError('can not determine fpot for angle %s ' %
                                        angle)

        samepotential = _isSameBondAnglePotential(ipot, fpot)

        if (not samepotential and
            ipot != "todefine" and
            (not _isSameBondAnglePotential(ipot, mpot) ) ):
            if (at0.name().value() not in zz_atoms or
                at1.name().value() not in zz_atoms or
                at2.name().value() not in zz_atoms):
                samepotential = False
            else:
                raise errors.SetupError('BUG: The initial and morph angles '
                                        'are different, but the potential does'
                                        'involve a dummy atom.')

        if idummy and fdummy:
            # This happens when we create 1-3 interactions involving two groups
            # of dummy atoms with some dummy in the initial state and some dummy
            # in the final state.  The best option is to use null parameters so
            # as not to artificially restraint the morph
            ipot = (0, 0)
            fpot = ipot
        elif idummy:
            ipot = fpot
        elif fdummy:
            fpot = ipot

        if (idummy or fdummy) or (not samepotential):
            i_force = ipot[0]
            i_eq = ipot[1]
            f_force = fpot[0]
            f_eq = fpot[1]

            if turnoffdummyangles and idummy:
                if (not at0.name().value().startsWith("DU") or
                    not at2.name().value().startsWith("DU") ):
                    i_force = 0.0
            if turnoffdummyangles and fdummy:
                if (not at0.name().value().startsWith("DU") or
                    not at2.name().value().startsWith("DU") ):
                    i_force = 0.0

            outstr = "\tangle\n"
            outstr += "\t\tatom0   %s\n" % at0.name().value()
            outstr += "\t\tatom1   %s\n" % at1.name().value()
            outstr += "\t\tatom2   %s\n" % at2.name().value()
            outstr += "\t\tinitial_force %s\n" % i_force
            outstr += "\t\tinitial_equil %s\n" % i_eq
            outstr += "\t\tfinal_force   %s\n" % f_force
            outstr += "\t\tfinal_equil   %s\n" % f_eq
            outstr += "\tendangle\n"

            pertfile.write(outstr)


    # Now dihedrals...
    #
    # JM 03/13
    # Problem: there could be some dihedrals/impropers that are not contained
    # in dihedrals_morph or dihedrals_initial
    # BUT do exist in dihedrals_final. These cases can be detected by looking
    # for dihedrals in the final topology that haven't been matched to
    # dihedrals in the morph
    #

    unmapped_fdihedrals = dihedrals_final

    for dihedral in dihedrals_morph:
        mpot = params_morph.getParams(dihedral)

        idummy = False
        fdummy = False
        allidummy = False
        allfdummy = False
        ipot = None

        at0 = new_morph.select(dihedral.atom0() )
        at1 = new_morph.select(dihedral.atom1() )
        at2 = new_morph.select(dihedral.atom2() )
        at3 = new_morph.select(dihedral.atom3() )

        at0i = at0.index()
        at1i = at1.index()
        at2i = at2.index()
        at3i = at3.index()

        for idihedral in dihedrals_initial:
            iat0 = lig_initial.select(idihedral.atom0() ).index()
            iat1 = lig_initial.select(idihedral.atom1() ).index()
            iat2 = lig_initial.select(idihedral.atom2() ).index()
            iat3 = lig_initial.select(idihedral.atom3() ).index()

            if ( (at0i == iat0 and at1i == iat1 and at2i == iat2 and at3i == iat3) or
                 (at0i == iat3 and at1i == iat2 and at2i == iat1 and at3i == iat0) ):
                ipot = params_initial.getParams(idihedral)

                break

        if not ipot:
            if (at0.name().value().startsWith("DU") or
                at1.name().value().startsWith("DU") or
                at2.name().value().startsWith("DU") or
                at3.name().value().startsWith("DU") ):
                ipot = "todefine"
                idummy = True
            else:
                raise errors.SetupError('Could not locate torsion parameters for '
                                        'the final state. This is most likely '
                                        'because the atom mapping would open '
                                        'up a ring in the intiial state.')

            allidummy = (at0.name().value().startsWith("DU") and
                         at1.name().value().startsWith("DU") and
                         at2.name().value().startsWith("DU") and
                         at3.name().value().startsWith("DU") )

        fpot = None

        map_at0 = util.search_atom(at0i, atom_map)
        map_at1 = util.search_atom(at1i, atom_map)
        map_at2 = util.search_atom(at2i, atom_map)
        map_at3 = util.search_atom(at3i, atom_map)

        for fdihedral in dihedrals_final:
            fat0 = lig_final.select(fdihedral.atom0() )
            fat1 = lig_final.select(fdihedral.atom1() )
            fat2 = lig_final.select(fdihedral.atom2() )
            fat3 = lig_final.select(fdihedral.atom3() )

            if ((map_at0 == fat0 and map_at1 == fat1 and map_at2 == fat2 and
                 map_at3 == fat3) or
                (map_at0 == fat3 and map_at1 == fat2 and map_at2 == fat1 and
                 map_at3 == fat0) ):
                fpot = params_final.getParams(fdihedral)
                unmapped_fdihedrals.remove(fdihedral)
                break

        if not fpot:
            if not map_at0 or not map_at1 or not map_at2 or not map_at3:
                fpot = "todefine"
                fdummy = True
            else:
                # This could be because the dihedral has a 0 force constant and
                # was not loaded from the top file. Flaw in the amber top parser?
                raise errors.SetupError('Cannot determine fpot for dihedral %s'
                                        % dihedral)

            # Check if all atoms are dummies in final torsion
            allfdummy = (not map_at0 and not map_at1 and
                         not map_at2 and not map_at3)

        samepotential = _isSameDihedralPotential(ipot, fpot)

        if (not samepotential and
            ipot != "todefine" and
            (not _isSameDihedralPotential(ipot, mpot) ) ):
            if (at0.name().value() not in zz_atoms or
                at1.name().value() not in zz_atoms or
                at2.name().value() not in zz_atoms or
                at3.name().value() not in zz_atoms):
                samepotential = False
            else:
                raise errors.SetupError('BUG: The initial and morph dihedrals '
                                        'are different, but the potential does '
                                        'not involve a dummy atom.')

        #
        # Unlike bonds/angles, dihedrals with dummies have no energy
        #
        if idummy and fdummy:
            # JM 03/13 This can happen in some morphs. Then use a null potential
            # throughout.
            ipot = [0.0, 0.0, 0.0]
            fpot = [0.0, 0.0, 0.0]
        elif idummy:
            ipot = [0.0, 0.0, 0.0]
            # Use parameters of final perturbation if all initial atoms are
            # dummies
            if allidummy:
                ipot = fpot
        elif fdummy:
            fpot = [0.0, 0.0, 0.0]
            if allfdummy:
                fpot = ipot

        # leap creates for some unkown reason zero torsions
        if len(ipot) == 3 and len(fpot) == 3 and \
               ipot[0] == 0.0 and fpot[0] == 0.0:
            continue

        if (idummy or fdummy) or (not samepotential):
            outstr = "\tdihedral\n"
            outstr += "\t\tatom0   %s\n" % at0.name().value()
            outstr += "\t\tatom1   %s\n" % at1.name().value()
            outstr += "\t\tatom2   %s\n" % at2.name().value()
            outstr += "\t\tatom3   %s\n" % at3.name().value()
            outstr += "\t\tinitial_form %s\n" % ' '.join([str(i) for i in ipot])
            outstr += "\t\tfinal_form %s\n" % ' '.join([str(f) for f in fpot])
            outstr += "\tenddihedral\n"

            pertfile.write(outstr)

    if unmapped_fdihedrals:
        logger.write("\ndihedrals in the final topology that haven't been "
                     "mapped to the initial topology:")
        logger.write(unmapped_fdihedrals)

    for fdihedral in unmapped_fdihedrals:
        fat0 = lig_final.select( fdihedral.atom0() ).index()
        fat1 = lig_final.select( fdihedral.atom1() ).index()
        fat2 = lig_final.select( fdihedral.atom2() ).index()
        fat3 = lig_final.select( fdihedral.atom3() ).index()

        fpot = params_final.getParams(fdihedral)
        ipot = [0.0, 0.0, 0.0]

        reversemap_at0 = util.search_atom(fat0, reverse_atom_map)
        reversemap_at1 = util.search_atom(fat1, reverse_atom_map)
        reversemap_at2 = util.search_atom(fat2, reverse_atom_map)
        reversemap_at3 = util.search_atom(fat3, reverse_atom_map)

        outstr = "\tdihedral\n"
        outstr += "\t\tatom0   %s\n" % reversemap_at0.value()
        outstr += "\t\tatom1   %s\n" % reversemap_at1.value()
        outstr += "\t\tatom2   %s\n" % reversemap_at2.value()
        outstr += "\t\tatom3   %s\n" % reversemap_at3.value()
        outstr += "\t\tinitial_form %s\n" % ' '.join([str(i) for i in ipot])
        outstr += "\t\tfinal_form %s\n" % ' '.join([str(f) for f in fpot])
        outstr += "\tenddihedral\n"

        pertfile.write(outstr)


    #
    # Now impropers...
    #

    unmapped_fimpropers = impropers_final
    unmapped_iimpropers = impropers_initial

    logger.write('\nimpropers:')

    for improper in impropers_morph:
        logger.write(improper)

        mpot = params_morph.getParams(improper)
        idummy = False
        fdummy = False
        allidummy = False
        allfdummy = False
        ipot = None

        at0 = new_morph.select( improper.atom0() )
        at1 = new_morph.select( improper.atom1() )
        at2 = new_morph.select( improper.atom2() )
        at3 = new_morph.select( improper.atom3() )

        at0i = at0.index()
        at1i = at1.index()
        at2i = at2.index()
        at3i = at3.index()

        for iimproper in impropers_initial:
            iat0 = lig_initial.select(iimproper.atom0() ).index()
            iat1 = lig_initial.select(iimproper.atom1() ).index()
            iat2 = lig_initial.select(iimproper.atom2() ).index()
            iat3 = lig_initial.select(iimproper.atom3() ).index()

            # Need different matching rules
            if ( ( at0i == iat0 or at0i == iat1 or at0i == iat2 or at0i == iat3) and
                 ( at1i == iat0 or at1i == iat1 or at1i == iat2 or at1i == iat3) and
                 ( at2i == iat0 or at2i == iat1 or at2i == iat2 or at2i == iat3) and
                 ( at3i == iat0 or at3i == iat1 or at3i == iat2 or at3i == iat3)
                 ):
                ipot = params_initial.getParams(iimproper)
                unmapped_iimpropers.remove(iimproper)
                break

        if not ipot:
            if (at0.name().value().startsWith("DU") or
                at1.name().value().startsWith("DU") or
                at2.name().value().startsWith("DU") or
                at3.name().value().startsWith("DU") ):
                ipot = "todefine"
                idummy = True
            else:
                raise errors.SetupError('Could not locate improper parameters for '
                                        'the final state. This is most likely '
                                        'because the atom mapping would open '
                                        'up a ring in the intiial state.')

            allidummy = (at0.name().value().startsWith("DU") and
                         at1.name().value().startsWith("DU") and
                         at2.name().value().startsWith("DU") and
                         at3.name().value().startsWith("DU") )

        fpot = None

        map_at0 = util.search_atom(at0i, atom_map)
        map_at1 = util.search_atom(at1i, atom_map)
        map_at2 = util.search_atom(at2i, atom_map)
        map_at3 = util.search_atom(at3i, atom_map)

        for fimproper in impropers_final:
            fat0 = lig_final.select(fimproper.atom0() )
            fat1 = lig_final.select(fimproper.atom1() )
            fat2 = lig_final.select(fimproper.atom2() )
            fat3 = lig_final.select(fimproper.atom3() )
            # The two matching rules below are to catch impropers that have been
            # defined by walking around the ring in a reverse order as in the
            # initial ligand
            # There are many equivalent ways of defining an improper
            #
            #       2
            #       |
            #       1
            #      / \
            #     0   3
            #
            # 0123 *
            # 0132 *
            # 2103 *
            # 2130 *
            # 3120 *
            # 3102 *
            # 3210 *
            # 2310 *
            # 3012 *
            # 0312 *
            # 0213 *
            # 2013 *

            if ( (map_at0 == fat0 or map_at0 == fat1 or map_at0 == fat2 or
                  map_at0 == fat3) and
                 (map_at1 == fat0 or map_at1 == fat1 or map_at1 == fat2 or
                  map_at1 == fat3) and
                 (map_at2 == fat0 or map_at2 == fat1 or map_at2 == fat2 or
                  map_at2 == fat3) and
                 (map_at3 == fat0 or map_at3 == fat1 or map_at3 == fat2 or
                  map_at3 == fat3) ):
                fpot = params_final.getParams(fimproper)
                unmapped_fimpropers.remove(fimproper)

                break

        if not fpot:
            if not map_at0 or not map_at1 or not map_at2 or not map_at3:
                fpot = "todefine"
                fdummy = True
            else:
                # JM 02/13 Found a case where one final improper does not exist,
                # but it does in the initial state...
                # R-NH2 --> R-NO2 this is at least for the gaff force field. It
                # seems then that a valid option is to guess a null improper in
                # those cases?

                fpot = [0.0, 0.0, 0.0]

            # Check if all atoms are dummies in final torsion
            allfdummy = (not map_at0 and not map_at1 and
                         not map_at2 and not map_at3)

#       print '=== impropers ==='
#       print (at0.name().value(), at1.name().value(),
#              at2.name().value(), at3.name().value(), ipot, fpot )
        samepotential = _isSameDihedralPotential(ipot, fpot)

        # FIXME: there is a logical problem here!
        if (not samepotential and
            ipot != "todefine" and
            (not _isSameDihedralPotential(ipot, mpot) ) ):
            if (at0.name().value() not in zz_atoms or
                at1.name().value() not in zz_atoms or
                at2.name().value() not in zz_atoms or
                at3.name().value() not in zz_atoms):
                samepotential = False
            else:
                raise errors.SetupError('BUG: The initial and morph impropers '
                                        'are different, but the potential does '
                                        'not involve a dummy atom.')

        if idummy and fdummy:
            ipot = [ 0.0, 0.0, 0.0 ]
            fpot = [ 0.0, 0.0, 0.0 ]
        elif idummy:
            ipot = [0.0, 0.0, 0.0]
            if allidummy:
                ipot = fpot
        elif fdummy:
            fpot = [0.0, 0.0, 0.0]
            if allfdummy:
                fpot = ipot

        ipotstr = ""
        for val in ipot:
            ipotstr += "%s " % val
        fpotstr = ""
        for val in fpot:
            fpotstr += "%s " % val

        if ( (idummy or fdummy) or (not samepotential) ):
            outstr = "\timproper\n"
            outstr += "\t\tatom0   %s\n" % at0.name().value()
            outstr += "\t\tatom1   %s\n" % at1.name().value()
            outstr += "\t\tatom2   %s\n" % at2.name().value()
            outstr += "\t\tatom3   %s\n" % at3.name().value()
            outstr += "\t\tinitial_form %s\n" % ipotstr
            outstr += "\t\tfinal_form %s\n" % fpotstr
            outstr += "\tendimproper\n"
            pertfile.write(outstr)

    logger.write("Impropers in the final topology that haven't been mapped to "
                 "the initial topology")
    logger.write(unmapped_fimpropers)

    for fimproper in unmapped_fimpropers:
        fat0 = lig_final.select( fimproper.atom0() ).index()
        fat1 = lig_final.select( fimproper.atom1() ).index()
        fat2 = lig_final.select( fimproper.atom2() ).index()
        fat3 = lig_final.select( fimproper.atom3() ).index()

        at0_info = util.search_atominfo(fat0, reverse_atom_map)
        at1_info = util.search_atominfo(fat1, reverse_atom_map)
        at2_info = util.search_atominfo(fat2, reverse_atom_map)
        at3_info = util.search_atominfo(fat3, reverse_atom_map)

        fpot = params_final.getParams(fimproper)

        if (not at0_info.atom and not at1_info.atom and
            not at2_info.atom and not at3_info.atom):
            ipot = fpot
        else:
            ipot = [0.0, 0.0, 0.0]

        outstr = "\timproper\n"
        outstr += "\t\tatom0   %s\n" % at0_info.name.value()
        outstr += "\t\tatom1   %s\n" % at1_info.name.value()
        outstr += "\t\tatom2   %s\n" % at2_info.name.value()
        outstr += "\t\tatom3   %s\n" % at3_info.name.value()
        outstr += "\t\tinitial_form %s\n" % ' '.join(str(i) for i in ipot)
        outstr += "\t\tfinal_form %s\n" % ' '.join(str(f) for f in fpot)
        outstr += "\tendimproper\n"

        pertfile.write(outstr)

    #
    # This happens for for instance acetamide --> acetone.
    # This breaks the assumption of the code that the morph contains all the dofs
    # of the initial state.  It could be because leap applies different rules to
    # decide whether to include impropers in a molecule, and the morph gets a
    # different treatment than for the initial state (owing to dummy atoms atoms)
    #
    # This suggests that a more robust version of the code should scan every
    # initial dof (bond/angle/dihedral/improper) match with final dof, and then
    # build the pert file, using the morph atom names (as opposed to assuming
    # that morph==initial for dofs  and then match final dofs to morph).
    #
    # For now, the code below should fix the missing improper problem
    #
    logger.write("Impropers in the initial topology that haven't been mapped "
                 "to the morph")
    logger.write(unmapped_iimpropers)

    for iimproper in unmapped_iimpropers:
        iat0 = lig_initial.select(iimproper.atom0() )
        iat1 = lig_initial.select(iimproper.atom1() )
        iat2 = lig_initial.select(iimproper.atom2() )
        iat3 = lig_initial.select(iimproper.atom3() )

        logger.write('%s %s %s %s' % (iat0, iat1, iat2, iat3) )

        ipot = params_initial.getParams(iimproper)
        fpot = [0.0, 0.0, 0.0]

        outstr = "\timproper\n"
        outstr += "\t\tatom0   %s\n" % iat0.name().value()
        outstr += "\t\tatom1   %s\n" % iat1.name().value()
        outstr += "\t\tatom2   %s\n" % iat2.name().value()
        outstr += "\t\tatom3   %s\n" % iat3.name().value()
        outstr += "\t\tinitial_form %s\n" % ' '.join(str(i) for i in ipot)
        outstr += "\t\tfinal_form %s\n" % ' '.join(str(f) for f in fpot)
        outstr += "\tendimproper\n"

        pertfile.write(outstr)

    pertfile.write('endmolecule\n')
    pertfile.close()
